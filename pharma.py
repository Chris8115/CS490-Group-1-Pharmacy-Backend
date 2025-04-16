from flask import Flask, request, Response, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, text
from flask_cors import CORS
from flasgger import Swagger, swag_from
import pika
import requests

HOST = 'localhost'
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=f"http://{HOST}:3000") 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pharma.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SWAGGER'] = {
    'title': 'BetterU API',
    'description': 'The available endpoints for the BetterU service.',
    'termsOfService': None,
    'doc_dir': './docs/',
    'uiversion': 3,
}

db = SQLAlchemy(app)
swag = Swagger(app)

def listen_for_orders():
    with app.app_context():
        def order_callback(ch, method, properties, body):
            (medication_id, patient_id) = body.decode().split(",")
            print(f"MESSAGE:: Medication ID: {medication_id} Patient ID: {patient_id}")
            try:
                db.session.execute(text("""
                    INSERT INTO orders (order_id, medication_id, status)
                    VALUES (
                        (SELECT MAX(order_id) FROM orders) + 1,
                        :med,
                        'pending'
                    )
                """), {'med': medication_id })
                
            except Exception as e:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                print(f"SQLITE ERROR:: {e}")
            else:
                db.session.commit()
                ch.basic_ack(delivery_tag=method.delivery_tag)
                print(requests.get(f"http://{HOST}:5000/patients?patient_id={patient_id}").json()) #Just testing rest call
                print("SQLITE:: Added order.")
        connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        channel = connection.channel()
        channel.queue_declare(queue='orders')
        channel.basic_consume(queue='orders', on_message_callback=order_callback)
        channel.start_consuming()

@app.route("/")
def home():
    return "<h1>It Works!</h1>"

@app.route("/inventory", methods=['GET'])
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

@app.route("/order_history", methods=['GET'])
@swag_from('docs/order/get.yml')
def get_order_history():
    query = "SELECT * FROM orders AS O JOIN medications AS M ON M.medication_id = O.medication_id\n"
    
    params = {
        'patient_id': "" if request.args.get('patient_id') is None else request.args.get('patient_id'),
    }

    if params['patient_id'] != "":
        query += (
            "WHERE " +
            ("patient_id = :patient_id\n" if params['patient_id'] != "" else "TRUE\n")
        )
    
    result = db.session.execute(text(query))
    json_response = {'orders': []}
    for row in result:
        json_response['orders'].append({
            'order_id': row.order_id,
            'medication_id': row.medication_id,
            'name': row.name,
            'status': row.status
        })
    return json_response, 200
        
def ResponseMessage(message, code):
    return {'message': message}, code

if __name__ == "__main__":
    import threading
    threading.Thread(target=listen_for_orders, daemon=True).start()
    app.run(debug=True, port=5001)