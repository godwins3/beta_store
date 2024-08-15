import threading
from django.core.mail import send_mail
from .models import Order

def send_order_email(order_id):
    """
    Function to send an e-mail notification when an order is
    successfully created or confirmed.
    """
    try:
        order = Order.objects.get(id=order_id)
        subject = f'Order nr. {order.order_number}'
        message = f'Dear {order.first_name},\n\n' \
                  f'You have successfully placed an order.' \
                  f'Your order number is {order.order_number}.'
        mail_sent = send_mail(subject,
                              message,
                              'admin@myshop.com',
                              [order.email])
        return mail_sent
    except Order.DoesNotExist:
        # Handle the case where the order does not exist
        print(f'Order with id {order_id} does not exist.')

def order_created(order_id):
    """
    Initiates the sending of an e-mail notification for an order creation.
    """
    thread = threading.Thread(target=send_order_email, args=(order_id,))
    thread.start()

def order_confirmed(order_id):
    """
    Initiates the sending of an e-mail notification for an order confirmation.
    """
    def send_confirmation_email():
        try:
            order = Order.objects.get(id=order_id)
            subject = f'Order nr. {order.order_number}'
            message = f'Dear {order.first_name},\n\n' \
                      f'Your order has been confirmed.' \
                      f'Your order ID is {order.order_number}.'
            mail_sent = send_mail(subject, message, 'admin@esoko.com', [order.email])
            return mail_sent
        except Order.DoesNotExist:
            print(f'Order with id {order_id} does not exist.')

    thread = threading.Thread(target=send_confirmation_email)
    thread.start()
