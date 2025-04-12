from flask import Flask, request, Response, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, text
from flask_cors import CORS
import pika
import requests

HOST = 'localhost'
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=f"http://{HOST}:3000") 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pharma.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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
        
def ResponseMessage(message, code):
    return {'message': message}, code

if __name__ == "__main__":
    import threading
    threading.Thread(target=listen_for_orders, daemon=True).start()
    app.run(debug=True, port=5001)