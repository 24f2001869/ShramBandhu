from flask import current_app
import razorpay ,  requests
from shrambandhu.config import Config
from datetime import datetime
import json

def get_razorpay_client():
    try:
        # Verify keys exist
        key_id = current_app.config.get('RAZORPAY_KEY_ID')
        key_secret = current_app.config.get('RAZORPAY_KEY_SECRET')

        if not key_id or not key_secret:
            raise ValueError("Missing Razorpay configuration")
        
        client = razorpay.Client(auth=(key_id, key_secret))

        # Optional: try a safe endpoint like fetching first order (if needed)
        # orders = client.order.all({'count': 1})  # Not needed unless you're testing
        
        return client

    except Exception as e:
        print(f"Razorpay Client Initialization Error: {str(e)}")
        raise

def create_payment_order(amount, job_id, employer_id, worker_id):
    try:
        client = get_razorpay_client()
        
        print(f"Creating payment: Amount={amount}, JobID={job_id}")
        print(f"Using Key: {current_app.config['RAZORPAY_KEY_ID'][:6]}...")
        
        amount_paise = int(float(amount) * 100)  # Ensure numeric conversion
        if amount_paise < 100:
            raise ValueError("Amount must be at least ₹1")

        order_data = {
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': f'job_{job_id}_{int(datetime.now().timestamp())}',
            'payment_capture': 1,
            'notes': {
                'job_id': job_id,
                'employer_id': employer_id,
                'worker_id': worker_id
            }
        }
        
        print("Order Data:", order_data)
        order = client.order.create(data=order_data)
        print("Order Response:", order)
        return order
        
    except razorpay.errors.BadRequestError as e:
        print(f"Razorpay API Error: {e.error}")
        raise Exception(f"Payment failed: {e.error.get('description', 'Unknown error')}")
    except Exception as e:
        print(f"Payment Processing Error: {str(e)}")
        raise

def verify_payment(payment_id):
    try:
        payment = client.payment.fetch(payment_id)
        
        # Check if payment is successful
        if payment['status'] == 'captured':
            return {
                'success': True,
                'payment_id': payment['id'],
                'amount': payment['amount'] / 100,  # Convert to rupees
                'notes': payment['notes']
            }
        return {'success': False}
    except Exception as e:
        print(f"Verification error: {str(e)}")
        return {'success': False}