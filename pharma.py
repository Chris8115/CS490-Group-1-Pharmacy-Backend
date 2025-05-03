from dotenv import load_dotenv
import os
load_dotenv()  

from flask import Flask, request, Response, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, text
from flask_cors import CORS
from flasgger import Swagger, swag_from
import pika
import requests
import json
from flask_login import LoginManager, UserMixin, login_user, LoginManager, login_required, logout_user, current_user
import re

HOST = 'localhost'
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=f"http://{HOST}:3000") 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pharma.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SWAGGER'] = {
    'title': 'BigPharma API',
    'description': 'The available endpoints for the BigPharma service.',
    'termsOfService': None,
    'doc_dir': './docs/',
    'uiversion': 3,
}

app.config['SECRET_KEY'] = os.getenv("CRAZE_SECRET_KEY") #super duper secret 🤫
app.config['SESSION_COOKIE_SECURE']=False

db = SQLAlchemy(app)
swag = Swagger(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Pharmacists, int(user_id))

class Pharmacists(db.Model, UserMixin):
    pharmacist_id = db.Column(db.Integer, primary_key=True)
    pharmacy_location = db.Column(db.Text, nullable=False)
    password = db.Column(db.Text, nullable=False)
    def get_id(self):
        return str(self.pharmacist_id)

def listen_for_orders():
    with app.app_context():
        def order_callback(ch, method, properties, body):
            (medication_id, patient_id) = body.decode().split(",")
            print(f"MESSAGE:: Medication ID: {medication_id} Patient ID: {patient_id}")
            try:
                db.session.execute(text("""
                    INSERT INTO orders (order_id, medication_id, status, patient_id)
                    VALUES (
                        (SELECT MAX(order_id) FROM orders) + 1,
                        :med,
                        'pending',
                        :pid
                    )
                """), {'med': medication_id, 'pid': patient_id})
                
            except Exception as e:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                print(f"SQLITE ERROR:: {e}")
            else:
                db.session.commit()
                ch.basic_ack(delivery_tag=method.delivery_tag)
                #print(requests.get(f"http://{HOST}:5000/patients?patient_id={patient_id}").json()) #Just testing rest call
                print("SQLITE:: Added order.")
        connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        channel = connection.channel()
        channel.queue_declare(queue='orders')
        channel.basic_consume(queue='orders', on_message_callback=order_callback)
        channel.start_consuming()

def listen_for_patients():
  with app.app_context():
        def patient_callback(ch, method, properties, body):
            params = json.loads(body.decode())
            print(f"MESSAGE:: JSON data: {body.decode()}")
            try:
                db.session.execute(text(f"""
                INSERT INTO patients (patient_id, first_name, last_name, medical_history, ssn)
                VALUES (
                    :patient_id,
                    :first_name,
                    :last_name,
                    :medical_history,
                    :ssn
                )
                """), params)
            except Exception as e:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                print(f"SQLITE ERROR:: {e}")
            else:
                db.session.commit()
                ch.basic_ack(delivery_tag=method.delivery_tag)
                print("SQLITE:: Added patient!")
        connection = pika.BlockingConnection(pika.ConnectionParameters(HOST))
        channel = connection.channel()
        channel.queue_declare(queue='patient_publish')
        channel.basic_consume(queue='patient_publish', on_message_callback=patient_callback)
        channel.start_consuming()

def send_order_update(params):
    message = json.dumps(params)
    connection = pika.BlockingConnection(pika.ConnectionParameters(HOST))
    channel = connection.channel()
    channel.queue_declare(queue='order_updates')
    channel.basic_publish(exchange='', routing_key='order_updates', body=message)
    print(f"Sent {message}")
    connection.close()

def send_new_medication(params):
    message = json.dumps(params)
    connection = pika.BlockingConnection(pika.ConnectionParameters(HOST))
    channel = connection.channel()
    channel.queue_declare(queue='new_medication')
    channel.basic_publish(exchange='', routing_key='new_medication', body=message)
    print(f"Sent {message}")
    connection.close()

def request_patient(patient_id):
    message = patient_id
    connection = pika.BlockingConnection(pika.ConnectionParameters(HOST))
    channel = connection.channel()
    channel.queue_declare(queue='patient_request')
    channel.basic_publish(exchange='', routing_key='patient_request', body=message)
    print(f"Requested patient {message}")
    connection.close()

@app.route("/")
def home():
    return f"""
        <h1>Pharmacy Index</h1>
        <ul>
            <li><a href='http://{HOST}:3000/'>Pharmacy Home</a></li>
            <li><a href='http://{HOST}:5001/apidocs'>API Documentation</a></li>
            <li><a href='http://{HOST}:15672/'>RabbitMQ Dashboard</a></li>
        </ul>"""

@app.route('/login', methods=['GET', 'POST'])
@swag_from("docs/auth/login_get.yml", methods=['GET'])
@swag_from("docs/auth/login_post.yml", methods=['POST'])
def login():
    if(request.args.get('next') != None):
        return ResponseMessage(f"Login Error: Login required to access route {request.args.get('next')}", 401)
    method_source = request.args if request.method == 'GET' else request.json
    params = {
        'pharmacist_id': method_source.get('pharmacist_id'),
        'password': method_source.get('password'),
        'remember': method_source.get('remember') if method_source.get('remember') != None else False
    }
    if((None, "") in list(params.values())[:-1]):
        return ResponseMessage("ID and password required.", 400)
    user = Pharmacists.query.filter_by(pharmacist_id=params['pharmacist_id']).first()
    if user == None:
        return ResponseMessage("Invalid user credentials.", 401)
    elif(user.password != params['password']):
        return ResponseMessage("Invalid password.", 401)
    else:
        login_user(user, params['remember'] or False)
        return {'pharmacist_id': current_user.pharmacist_id, 'pharmacy_location': current_user.pharmacy_location, 'message':'Login successful.'}, 200

@app.route('/logout', methods=['GET', 'POST'])
@login_required
@swag_from('docs/auth/logout.yml', methods=['GET', 'POST'])
def logout():
    logout_user()
    return ResponseMessage("User Logged out.", 200)

@app.route('/login_check')
@login_required
@swag_from('docs/auth/login_check.yml')
def login_check():
    return ResponseMessage(f"User is logged in. ID: {current_user.get_id()}", 200)

@app.route("/inventory", methods=['GET'])
@login_required
@swag_from('docs/inventory/get.yml')
def get_inventory():
    query = "SELECT * FROM inventory\n"

    params = {
        'inv_id': "" if request.args.get('inventory_id') is None else request.args.get('inventory_id'),
        'med_id': "" if request.args.get('medication_id') is None else request.args.get('medication_id'),
        'stock': "" if request.args.get('stock') is None else request.args.get('stock'),
        'last_updated': "" if request.args.get('last_updated') is None else '%' + request.args.get('last_updated') + '%'
    }
    if params['inv_id'] != "" or params['med_id'] != "" or params['stock'] != "" or params['last_updated'] != "":
        query += (
            "WHERE " +
            ("inventory_id = :inv_id\n" if params['inv_id'] != "" else "TRUE\n") +
            "AND " + ("medication_id = :med_id\n" if params['med_id'] != "" else "TRUE\n") +
            "AND " + ("stock = :stock\n" if params['stock'] != "" else "TRUE\n") +
            "AND " + ("last_updated LIKE :last_updated\n" if params['last_updated'] != "" else "TRUE\n")
        )

    result = db.session.execute(text(query), params)
    json_response = {'inventory': []}
    for row in result:
        json_response['inventory'].append({
            'inventory_id': row.inventory_id,
            'medication_id': row.medication_id,
            'stock': row.stock,
            'last_updated': row.last_updated
        })
    return json_response, 200

@app.route("/medications", methods=['POST'])
@login_required
@swag_from("docs/medications/post.yml")
def add_medications():
    params = {
        'name': request.json.get('name'),
        'description': request.json.get('description')
    }
    query = text("""
        INSERT INTO medications (medication_id, name, description)
        VALUES (
            (SELECT MAX(medication_id) FROM medications) + 1,
            :name,
            :description
        )
    """)
    #input validation
    if(any(tok in params.values() for tok in (None, ""))):
        return ResponseMessage("Required parameters not sent.", 400)
    try:
        db.session.execute(query, params)
    except Exception as e:
        print(e)
        return ResponseMessage("Server error, please try again later.", 500)
    else:
        db.session.commit()
        send_new_medication(params)
        return ResponseMessage("Medication Added.", 201)

@app.route("/medications", methods=['GET'])
@login_required
@swag_from('docs/medications/get.yml')
def get_medications():
    # SQL query to fetch medications
    query = "SELECT * FROM medications\n"
    # Gather optional parameters
    params = {
        'med_id': "" if request.args.get('medication_id') is None else request.args.get('medication_id'),
        'name': "" if request.args.get('name') is None else '%' + request.args.get('name') + '%',
        'description': "" if request.args.get('description') is None else '%' + request.args.get('description') + '%'
    }
    if params['med_id'] != "" or params['name'] != "" or params['description'] != "":
        query += (
            "WHERE " +
            ("medication_id = :med_id\n" if params['med_id'] != "" else "TRUE\n") +
            "AND " + ("name LIKE :name\n" if params['name'] != "" else "TRUE\n") +
            "AND " + ("description LIKE :description\n" if params['description'] != "" else "TRUE\n")
        )
    # Execute query and build JSON response
    result = db.session.execute(text(query), params)
    json_response = {'medications': []}
    for row in result:
        json_response['medications'].append({
            'medication_id': row.medication_id,
            'name': row.name,
            'description': row.description
        })
    return json_response, 200

@app.route('/orders/<int:order_id>', methods=['PATCH'])
@login_required
@swag_from('docs/orders/patch.yml')
def update_order(order_id):
    params = {
        'order_id': order_id,
        'medication_id': request.json.get('medication_id'),
        'status': request.json.get('status'),
        'patient_id': request.json.get('patient_id')
    }
    query = text(f"""
        UPDATE orders SET
            medication_id = {':medication_id' if params['medication_id'] != None else 'medication_id'},
            status = {':status' if params['status'] != None else 'status'},
            patient_id = {':patient_id' if params['patient_id'] != None else 'patient_id'}
        WHERE order_id = :order_id
    """)
    #input validation
    if(all(param == None for param in list(params.values())[1:])):
        return ResponseMessage("Updated nothing.", 200)
    if(not ValidTableID('orders', 'order_id', order_id)):
        return ResponseMessage("Invalid Order ID.", 404)
    if(params['medication_id'] != None and not ValidTableID('medications', 'medication_id', params['medication_id'])):
        return ResponseMessage("Invalid Medication ID.", 400)
    if(params['status'] != None and params['status'].lower() not in ('accepted', 'rejected', 'pending', 'canceled', 'ready')):
        return ResponseMessage("Invalid status. (must be 'accepted', 'rejected', 'pending', 'canceled', or 'ready')", 400)
    #database update
    try:
        db.session.execute(query, params)
    except Exception as e:
        print(e)
        return ResponseMessage("Server error updating order.", 500)
    else:
        db.session.commit()
        send_order_update(params)
        return ResponseMessage("Order Updated.", 200)

@app.route('/patient/<int:patient_id>', methods=['GET'])
@login_required
@swag_from('docs/patient/get.yml')
def get_patient(patient_id):
    patient =  requests.get(f"http://{HOST}:5000/patients?patient_id={patient_id}").json()['patients']
    user = requests.get(f"http://{HOST}:5000/users?user_id={patient_id}").json()['users']
    print(patient)
    if([] in (patient, user)):
        return ResponseMessage("Invalid patient!", 400)
    patient = patient[0]
    user = user[0]
    return {'patient': {
        'patient_id': patient['patient_id'],
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'medical_history': patient['medical_history'],
        'ssn': patient['ssn']
    }}, 200

@app.route('/patients', methods=['GET'])
@login_required
@swag_from('docs/patients/get.yml')
def get_patients():
    query = text(f"""
        SELECT * FROM patients
        WHERE {'first_name LIKE :first_name' if request.args.get('first_name') else 'TRUE'}
        AND {'last_name LIKE :last_name' if request.args.get('last_name') else 'TRUE'}
        AND {'patient_id = :patient_id' if request.args.get('patient_id') else 'TRUE'}
        AND {'medical_history LIKE :medical_history' if request.args.get('medical_history') else 'TRUE'}
    """)
    params = {
        'patient_id': request.args.get('patient_id'),
        'first_name': f"%{request.args.get('first_name')}%",
        'last_name': f"%{request.args.get('last_name')}%",
        'medical_history': f"%{request.args.get('medical_history')}%"
    }
    result = db.session.execute(query, params)
    response_json = {"patients":[]}
    for row in result:
        response_json['patients'].append({
            'patient_id': row.patient_id,
            'first_name': row.first_name,
            'last_name': row.last_name,
            'medical_history': row.medical_history,
            'ssn': row.ssn
        })
    return response_json, 200
    

@app.route("/orders", methods=['GET'])
@login_required
@swag_from('docs/orders/get.yml')
def get_orders():
    query = "SELECT O.*, M.name, P.first_name, P.last_name FROM orders AS O JOIN medications AS M ON M.medication_id = O.medication_id INNER JOIN patients AS P on O.patient_id = P.patient_id\n"
    params = {
        'order_id': "" if request.args.get('order_id') is None else request.args.get('order_id'),
        'medication_id': "" if request.args.get('medication_id') is None else request.args.get('medication_id'),
        'status': "" if request.args.get('status') is None else '%' + request.args.get('status') + '%',
        'patient_id': "" if request.args.get('patient_id') is None else request.args.get('patient_id'),
        'order_by': "DESC" if request.args.get('order_by') == None else request.args.get('order_by')
    }
    
    conditions = []
    if params['order_id'] != "":
        conditions.append("O.order_id = :order_id")
    if params['medication_id'] != "":
        conditions.append("O.medication_id = :medication_id")
    if params['status'] != "":
        conditions.append("O.status LIKE :status")
    if params['patient_id'] != "":
        conditions.append("O.patient_id = :patient_id")
    
    if conditions:
        query += "WHERE " + " AND ".join(conditions) + "\n"
    query += (f"ORDER BY order_id {'ASC' if params['order_by'].upper() == 'ASC' else 'DESC'}")
    
    result = db.session.execute(text(query), params)
    json_response = {'orders': []}
    for row in result:
        json_response['orders'].append({
            'order_id': row.order_id,
            'medication_id': row.medication_id,
            'name': row.name,
            'status': row.status,
            'patient_id': row.patient_id,
            'first_name': row.first_name,
            'last_name': row.last_name
        })
    return json_response, 200

def ValidTableID(table:str, id_field:str, id:int):
    return db.session.execute(text(f"SELECT * FROM {table} WHERE {id_field} = :id"), {'id': id}) != None
        
def ResponseMessage(message, code):
    print(f"REST call returned with code {code},\nMessage: {message}")
    return {'message': message}, code

if __name__ == "__main__":
    import threading
    threading.Thread(target=listen_for_orders, daemon=True).start()
    threading.Thread(target=listen_for_patients, daemon=True).start()
    app.run(debug=True, port=5001)
