import datetime as dt
import json
from secrets import compare_digest
import requests
from requests.auth import HTTPBasicAuth
from decimal import Decimal

from django.conf import settings
from django.db.transaction import atomic, non_atomic_requests
from django.http import HttpResponse ,HttpResponseForbidden ,JsonResponse
from django.views import View
from django.views.generic import DetailView,TemplateView,FormView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from django.shortcuts import render, redirect,get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.urls import reverse

from orders.models import Order
from . mpesa import MpesaAccessToken,LipaNaMpesaPassword
from .models import MpesaPayment
from .forms import MpesaNumberForm


def getAccessToken(request):
    consumer_key = settings.MPESA_CONSUMER_KEY
    consumer_secret = settings.MPESA_CONSUMER_SECRET
    api_URL = settings.MPESA_API_URL

    r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret))
    mpesa_access_token = json.loads(r.text)
    validated_mpesa_access_token = mpesa_access_token['access_token']

    return HttpResponse(validated_mpesa_access_token)

 

class MpesaNumberView(LoginRequiredMixin,FormView):
    '''
    a view that renders a form for the user to enter their  mpesa phone number,
    during checkout
    '''
    form_class = MpesaNumberForm
    template_name = 'payments/mpesa_number.html'

    def form_valid(self, form):
        phone_number = form.cleaned_data['phone_number']
        self.request.session['phone_number'] = phone_number
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('payment:lipa_na_mpesa')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get('order_id', None)
        order = get_object_or_404(Order, id=order_id)
        context['order'] = order
        return context



@csrf_exempt
@non_atomic_requests
def lipa_na_mpesa(request):
    order_id = request.session['order_id']
    order = get_object_or_404(Order, id=order_id)
    total_cost = order.get_total_cost()
    amount=float(total_cost)
    phone_number = request.session['phone_number']
    
    access_token = MpesaAccessToken.validated_mpesa_access_token
    '''
    if not compare_digest(access_token, ''): #we compare the access token to an empty string/invalid token
        return HttpResponseForbidden(
            'Invalid access token. Please generate a new one and try again.',
            content_type='text/plain'
        )
    '''

    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {"Authorization": "Bearer %s" % access_token}
    request = {
        "BusinessShortCode": LipaNaMpesaPassword.Business_short_code,
        "Password": LipaNaMpesaPassword.decode_password,
        "Timestamp": LipaNaMpesaPassword.lipa_time,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA":phone_number, 
        "PartyB": LipaNaMpesaPassword.Business_short_code,
        "PhoneNumber":phone_number, 
        "CallBackURL": "https://sandbox.safaricom.co.ke/mpesa/",
        "AccountReference": "Beta Milk",
        "TransactionDesc": "Testing stk push"
    }

    response =requests.post(api_url, json=request, headers=headers)
    # return JsonResponse(response.json())
    return redirect('/')



@method_decorator(csrf_exempt, name='dispatch')
class MpesaStkPushCallbackView(View):
    def post(self, request):
        data = json.loads(request.body)['Body']['stkCallback']
        
        if data['ResultCode'] == 0:
            # if payment was successful
             try:
                with atomic():
                    MpesaPayment.objects.create(
                        MerchantRequestID=data['MerchantRequestID'],
                        CheckoutRequestID=data['CheckoutRequestID'],
                        ResultCode=data['ResultCode'],
                        ResultDesc=data['ResultDesc'],
                        Amount=data['CallbackMetadata']['Item'][0]['Value'],
                        MpesaReceiptNumber=data['CallbackMetadata']['Item'][1]['Value'],
                        Balance=data['CallbackMetadata']['Item'][2]['Value'],
                        TransactionDate=data['CallbackMetadata']['Item'][3]['Value'],
                        PhoneNumber=data['CallbackMetadata']['Item'][4]['Value'],
                    )
                    order_id = request.session['order_id']
                    order = get_object_or_404(Order, id=order_id)
                    order.paid = True
                    order.save()
                    return redirect(reverse('payment:payment_completed'))
             except IntegrityError:
                return HttpResponse('Payment already exists')

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Success", "ThirdPartyTransID": 0})



@csrf_exempt
def mpesa_webhook(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        #get post data from safaricom and save it to the database
        MpesaPayment.objects.create(
            MerchantRequestID=data['MerchantRequestID'],
            CheckoutRequestID=data['CheckoutRequestID'],
            ResultCode=data['ResultCode'],
            ResultDesc=data['ResultDesc'],
            Amount=data['CallbackMetadata']['Item'][0]['Value'],
            MpesaReceiptNumber=data['CallbackMetadata']['Item'][1]['Value'],
            Balance=data['CallbackMetadata']['Item'][2]['Value'],
            TransactionDate=data['CallbackMetadata']['Item'][3]['Value'],
            PhoneNumber=data['CallbackMetadata']['Item'][4]['Value'],
        )
        #get the order id from the session,and get the order object,then set the order to paid
        order_id = request.session['order_id']
        order = get_object_or_404(Order, id=order_id)
        order.paid = True
        order.save()

        return HttpResponse('success')
    else:
        return HttpResponse('error')



@csrf_exempt
def register_urls(request):
    access_token = MpesaAccessToken.validated_mpesa_access_token
    api_url = "https://sandbox.safaricom.co.ke/mpesa/c2b/v1/registerurl"
    headers = {"Authorization": "Bearer %s" % access_token}
    options = {"ShortCode": LipaNaMpesaPassword.Test_c2b_shortcode,
               "ResponseType": "Completed",
               "ConfirmationURL": "https://8597-102-222-146-36.in.ngrok.io",
               "ValidationURL": "https://8597-102-222-146-36.in.ngrok.io"}
    response = requests.post(api_url, json=options, headers=headers)

    return HttpResponse(response.text)


@csrf_exempt
def call_back(request):
    pass


@csrf_exempt
def validation(request):

    context = {
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    }
    return JsonResponse(dict(context))



class PayviaMpesaonDeliveryView(DetailView):
    template_name = 'payments/mpesa_on_delivery.html'

    def get_object(self):
        order_id = self.request.session['order_id']
        order = Order.objects.get(id=order_id)
        return order


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get('order_id', None)
        order = get_object_or_404(Order, id=order_id)
        context['order'] = order
        return context



class BankTransferView(DetailView):
    template_name = 'payments/bank_transfer.html'

    def get_object(self):
        order_id = self.request.session['order_id']
        order = Order.objects.get(id=order_id)
        return order


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get('order_id', None)
        order = get_object_or_404(Order, id=order_id)
        context['order'] = order
        return context

    

class PaymentCompletedView(LoginRequiredMixin,TemplateView):
    template_name = 'payments/completed.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get('order_id', None)
        order = get_object_or_404(Order, id=order_id)
        context['order'] = order
        return context

    def get(self, request, *args, **kwargs):
        if 'order_id' in request.session:
            del request.session['order_id']
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if 'order_id' in request.session:
            del request.session['order_id']
        return super().post(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if 'order_id' not in request.session:
            messages.error(request, 'You have no orders')
            return redirect(reverse('orders:order_list'))
        return super().dispatch(request, *args, **kwargs)
    
    def get_success_url(self):
        return reverse('orders:order_list')

        
class PaymentCancelledView(LoginRequiredMixin,TemplateView):
    template_name = 'payments/cancelled.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order_id = self.request.session.get('order_id', None)
        order = get_object_or_404(Order, id=order_id)
        context['order'] = order
        return context

    def get(self, request, *args, **kwargs):
        if 'order_id' in request.session:
            del request.session['order_id']
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if 'order_id' in request.session:
            del request.session['order_id']
        return super().post(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if 'order_id' not in request.session:
            messages.error(request, 'You have no orders')
            return redirect(reverse('orders:order_list'))
        return super().dispatch(request, *args, **kwargs)
    
    def get_success_url(self):
        return reverse('orders:order_list')
      