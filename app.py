import os, re, secrets, smtplib, base64, datetime, hashlib
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, make_response
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError

load_dotenv()
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY") or "local-development-only-change-this-secret"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE","true").lower()=="true",
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE","Lax"),
    MAX_CONTENT_LENGTH=3*1024*1024
)
COMPANY = os.getenv("COMPANY_NAME","KIMATHI Furniture")
PHONE = os.getenv("ADMIN_PHONE","0702781490")
LOCATION = os.getenv("DEFAULT_LOCATION","Kimathi, Nyeri")
PRODUCTS = [
 {"name":"Armed Office Chair","price":12500,"category":"Seating","image":"armed-officechair.png","description":"Comfort-led seating for focused work."},
 {"name":"Bedroom Collection","price":42000,"category":"Bedroom","image":"bed.png","description":"A calmer foundation for your space."},
 {"name":"Work Desk","price":18500,"category":"Office","image":"desks.png","description":"Clean lines for a considered workspace."},
 {"name":"Dining Table","price":35000,"category":"Dining","image":"landing-dining.png","description":"Gather around timeless craftsmanship."},
 {"name":"Living Room Set","price":68000,"category":"Living","image":"landing2-nicetableroom.png","description":"Thoughtful comfort for everyday living."},
 {"name":"Wood Frame Mirrors","price":8500,"category":"Decor","image":"mirrors-wood-designframes.png","description":"Warm natural texture and useful detail."},
 {"name":"Furniture Set","price":55000,"category":"Living","image":"nice-furnitures.png","description":"Versatile pieces for modern homes."},
 {"name":"Premium Furniture","price":48000,"category":"Living","image":"nice2-fur.png","description":"Designed to live beautifully."},
 {"name":"Home Essentials","price":22000,"category":"Living","image":"other-furnitures.png","description":"Finishing touches for your home."},
 {"name":"Reception Desk","price":39000,"category":"Office","image":"reception-desk.png","description":"Make a confident first impression."},
 {"name":"Wooden Serving Plates","price":2800,"category":"Decor","image":"wooden-plates.png","description":"Natural wood for everyday hosting."}
]
client = db = None
try:
    uri = os.getenv("MONGODB_URI","").strip()
    if uri and "REPLACE_PASSWORD" not in uri and "<" not in uri:
        client = MongoClient(uri, serverSelectionTimeoutMS=2500, connectTimeoutMS=2500)
        db = client[os.getenv("MONGODB_DB","kimathi_furniture")]
except Exception:
    client = db = None

def now(): return datetime.datetime.now(datetime.timezone.utc)
def coll(name): return db[name] if db is not None else None
def record(name, doc):
    c=coll(name)
    if c is not None:
        doc.setdefault("created_at", now())
        c.insert_one(doc)
def rows(name, limit=100):
    c=coll(name)
    if c is None: return []
    try: return list(c.find({}, {"_id":0}).sort("created_at",DESCENDING).limit(limit))
    except Exception: return []
def setting(key, default=None):
    c=coll("settings")
    if c is not None:
        try:
            item=c.find_one({"key":key})
            if item: return item.get("value",default)
        except Exception: pass
    return default
def set_setting(key,value):
    c=coll("settings")
    if c is not None: c.update_one({"key":key},{"$set":{"value":value}},upsert=True)
    else: session["setting_"+key]=value
def get_setting(key,default=None): return setting(key, session.get("setting_"+key,default))

def admin_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get("is_admin"): return redirect(url_for("admin_login"))
        return fn(*a,**kw)
    return wrapped

def send_email(to, subject, body, html=None):
    host=os.getenv("SMTP_HOST"); username=os.getenv("SMTP_USERNAME"); password=os.getenv("SMTP_PASSWORD")
    if not all([host,username,password,to]): return False
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=os.getenv("SMTP_FROM",username); msg["To"]=to
    msg.set_content(body)
    if html: msg.add_alternative(html,subtype="html")
    with smtplib.SMTP(host,int(os.getenv("SMTP_PORT","587")),timeout=15) as server:
        if os.getenv("SMTP_USE_TLS","true").lower()=="true": server.starttls()
        server.login(username,password); server.send_message(msg)
    return True

@app.before_request
def visitor_log():
    if request.path.startswith("/static/") or request.path.startswith("/api/") or request.path.startswith("/admin"): return
    try: record("visitors",{"path":request.path,"referrer":request.referrer or "direct","user_agent":request.user_agent.string[:250],"ip_hash":hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:16],"at":now()})
    except Exception: pass

@app.context_processor
def globals_for_templates():
    return {"company":COMPANY,"phone":get_setting("admin_phone",PHONE),"location":get_setting("location",LOCATION),"cart_count":len(session.get("cart",[]))}

@app.route("/")
def home():
    return render_template("home.html", products=PRODUCTS, videos=["kimathi_furniture_premium_logo_ad.mp4","kimathi_furniture_logo_reveal.mp4"])

@app.route("/product/<slug>")
def product(slug):
    try: i=int(slug)
    except: abort(404)
    if i<0 or i>=len(PRODUCTS): abort(404)
    return render_template("product.html",p=PRODUCTS[i],idx=i)

@app.post("/cart/add")
def cart_add():
    i=request.form.get("product_id","")
    if not i.isdigit() or int(i)>=len(PRODUCTS): return jsonify(ok=False,error="Invalid item"),400
    cart=session.get("cart",[])
    cart.append(int(i)); session["cart"]=cart
    return jsonify(ok=True,count=len(cart))

@app.get("/cart")
def cart():
    items=[{"idx":i,**PRODUCTS[i]} for i in session.get("cart",[]) if 0<=i<len(PRODUCTS)]
    return render_template("cart.html",items=items,total=sum(p["price"] for p in items))

@app.post("/cart/remove")
def cart_remove():
    cart=session.get("cart",[])
    try: idx=int(request.form.get("index","-1"))
    except: idx=-1
    if 0<=idx<len(cart): cart.pop(idx); session["cart"]=cart
    return redirect(url_for("cart"))

@app.route("/checkout",methods=["GET","POST"])
def checkout():
    items=[{"idx":i,**PRODUCTS[i]} for i in session.get("cart",[]) if 0<=i<len(PRODUCTS)]
    if not items: flash("Your bag is empty."); return redirect(url_for("home"))
    if request.method=="POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip(); delivery=request.form.get("delivery","").strip()
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or not phone:
            flash("Enter your name, valid email and phone number."); return redirect(url_for("checkout"))
        order_id=secrets.token_hex(5).upper()
        total=sum(p["price"] for p in items)
        order={"order_id":order_id,"customer_name":name,"email":email,"phone":phone,"delivery_address":delivery,"items":[{"name":p["name"],"price":p["price"],"image":p["image"]} for p in items],"amount":total,"status":"Pending payment","payment_status":"unpaid","created_at":now()}
        record("orders",order)
        session["cart"]=[]
        if get_setting("purchase_email_otp_enabled",os.getenv("PURCHASE_EMAIL_OTP_ENABLED","false").lower()=="true"):
            code=f"{secrets.randbelow(1000000):06d}"
            session["checkout_otp"]={"order_id":order_id,"email":email,"hash":hashlib.sha256(code.encode()).hexdigest(),"expires":(now()+datetime.timedelta(minutes=10)).timestamp()}
            try: send_email(email,f"{COMPANY} email verification",f"Your verification code is {code}. It expires in 10 minutes.")
            except Exception: pass
            return redirect(url_for("verify_email"))
        return redirect(url_for("payment",order_id=order_id))
    return render_template("checkout.html",items=items,total=sum(p["price"] for p in items))

@app.route("/verify-email",methods=["GET","POST"])
def verify_email():
    state=session.get("checkout_otp")
    if not state: return redirect(url_for("home"))
    if request.method=="POST":
        code=request.form.get("code","")
        if now().timestamp()>state["expires"]: flash("Code expired. Please restart checkout."); session.pop("checkout_otp",None); return redirect(url_for("home"))
        if secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest(),state["hash"]):
            session.pop("checkout_otp",None); return redirect(url_for("payment",order_id=state["order_id"]))
        flash("That code is not correct.")
    return render_template("verify.html",email=state["email"])

@app.route("/payment/<order_id>")
def payment(order_id):
    order=find_order(order_id)
    if not order: abort(404)
    return render_template("payment.html",order=order)

def find_order(order_id):
    c=coll("orders")
    if c is not None:
        try: return c.find_one({"order_id":order_id},{"_id":0})
        except Exception: pass
    return None

def mpesa_token():
    key=os.getenv("MPESA_CONSUMER_KEY",""); secret=os.getenv("MPESA_CONSUMER_SECRET","")
    if not key or not secret: raise ValueError("M-Pesa credentials are not configured.")
    auth=base64.b64encode(f"{key}:{secret}".encode()).decode()
    base=os.getenv("DARAJA_BASE_URL","https://api.safaricom.co.ke").rstrip("/")
    r=requests.get(base+"/oauth/v1/generate?grant_type=client_credentials",headers={"Authorization":"Basic "+auth},timeout=15)
    r.raise_for_status(); return r.json()["access_token"]

@app.post("/api/mpesa/stkpush")
def stkpush():
    data=request.get_json(silent=True) or request.form
    order_id=str(data.get("order_id",""))
    order=find_order(order_id)
    if not order: return jsonify(ok=False,error="Order not found"),404
    phone=re.sub(r"\D","",str(data.get("phone") or order.get("phone","")))
    if phone.startswith("0"): phone="254"+phone[1:]
    if phone.startswith("+"): phone=phone[1:]
    if not re.fullmatch(r"254[17]\d{8}",phone): return jsonify(ok=False,error="Use a valid Kenyan M-Pesa number, e.g. 0712345678."),400
    shortcode=os.getenv("MPESA_BUSINESS_SHORT_CODE","").strip()
    till=os.getenv("MPESA_VENDOR_TILL","").strip()
    passkey=os.getenv("MPESA_PASSKEY","").strip()
    callback=os.getenv("MPESA_CALLBACK_URL","").strip()
    if not all([shortcode,till,passkey,callback]) or not callback.startswith("https://"):
        return jsonify(ok=False,error="M-Pesa setup incomplete. Admin must configure shortcode, passkey and HTTPS callback."),503
    try:
        token=mpesa_token()
        stamp=now().astimezone(datetime.timezone(datetime.timedelta(hours=3))).strftime("%Y%m%d%H%M%S")
        password=base64.b64encode((shortcode+passkey+stamp).encode()).decode()
        amount=max(1,int(round(float(order["amount"]))))
        payload={"BusinessShortCode":shortcode,"Password":password,"Timestamp":stamp,"TransactionType":os.getenv("MPESA_TRANSACTION_TYPE","CustomerBuyGoodsOnline"),"Amount":amount,"PartyA":phone,"PartyB":till,"PhoneNumber":phone,"CallBackURL":callback,"AccountReference":order_id,"TransactionDesc":f"{COMPANY} order {order_id}"}
        base=os.getenv("DARAJA_BASE_URL","https://api.safaricom.co.ke").rstrip("/")
        res=requests.post(base+"/mpesa/stkpush/v1/processrequest",json=payload,headers={"Authorization":"Bearer "+token},timeout=25)
        body=res.json()
        record("payments",{"order_id":order_id,"amount":amount,"phone":phone,"request_payload":{k:v for k,v in body.items() if k!="Password"},"created_at":now()})
        if res.ok and body.get("ResponseCode")=="0":
            c=coll("orders")
            if c is not None: c.update_one({"order_id":order_id},{"$set":{"checkout_request_id":body.get("CheckoutRequestID"),"merchant_request_id":body.get("MerchantRequestID"),"status":"STK prompt sent"}})
            return jsonify(ok=True,message="STK prompt requested. Check your phone and enter your M-Pesa PIN to authorize.",checkout_request_id=body.get("CheckoutRequestID"))
        return jsonify(ok=False,error=body.get("errorMessage") or body.get("ResponseDescription") or "Safaricom did not accept the STK request."),502
    except Exception as e:
        app.logger.exception("STK request failed")
        return jsonify(ok=False,error=str(e) if app.debug else "Payment service is temporarily unavailable. Check server configuration and try again."),502

@app.post("/api/mpesa/callback")
def mpesa_callback():
    body=request.get_json(silent=True) or {}
    meta=body.get("Body",{}).get("stkCallback",{})
    checkout_id=meta.get("CheckoutRequestID")
    result_code=meta.get("ResultCode")
    metadata={x.get("Name"):x.get("Value") for x in meta.get("CallbackMetadata",{}).get("Item",[])}
    c=coll("orders")
    if c is not None and checkout_id:
        order=c.find_one({"checkout_request_id":checkout_id})
        if order:
            updates={"mpesa_result_code":result_code,"mpesa_result_desc":meta.get("ResultDesc","")}
            if str(result_code)=="0":
                updates.update({"payment_status":"paid","status":"Paid","mpesa_receipt":metadata.get("MpesaReceiptNumber"),"paid_at":now()})
                for item in order.get("items",[]):
                    pass
            else: updates.update({"payment_status":"failed","status":"Payment failed"})
            c.update_one({"_id":order["_id"]},{"$set":updates})
            record("payments",{"order_id":order["order_id"],"callback":body,"result_code":result_code,"created_at":now()})
    return jsonify(ResultCode=0,ResultDesc="Accepted")

@app.get("/receipt/<order_id>")
def receipt(order_id):
    order=find_order(order_id)
    if not order: abort(404)
    return render_template("receipt.html",order=order)

@app.get("/track/<order_id>")
def track(order_id):
    order=find_order(order_id)
    if not order: abort(404)
    # Public tracking deliberately excludes email, phone and address.
    return render_template("track.html",order={"order_id":order.get("order_id"),"status":order.get("status"),"payment_status":order.get("payment_status"),"amount":order.get("amount"),"created_at":order.get("created_at")})

@app.route("/admin",methods=["GET"])
def admin_home():
    if not session.get("is_admin"): return redirect(url_for("admin_login"))
    orders=rows("orders",100); expenses=rows("expenses",100); visitors=rows("visitors",100)
    paid=sum(float(o.get("amount",0)) for o in orders if o.get("payment_status")=="paid")
    spent=sum(float(e.get("amount",0)) for e in expenses)
    return render_template("admin.html",orders=orders,expenses=expenses,visitors=visitors,paid=paid,spent=spent,products=PRODUCTS,db_ready=db is not None,otp_enabled=get_setting("purchase_email_otp_enabled",os.getenv("PURCHASE_EMAIL_OTP_ENABLED","false").lower()=="true"))

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        pw=request.form.get("password","")
        configured=os.getenv("ADMIN_PASSWORD","")
        if configured and configured!="SET-A-LONG-UNIQUE-PASSWORD" and secrets.compare_digest(pw,configured):
            session.clear(); session["is_admin"]=True; session.permanent=True
            record("admin_audit",{"event":"admin_login","at":now()})
            return redirect(url_for("admin_home"))
        flash("Invalid admin password. Set ADMIN_PASSWORD in your environment.")
    return render_template("admin_login.html")

@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear(); return redirect(url_for("home"))

@app.post("/admin/expense")
@admin_required
def add_expense():
    label=request.form.get("label","").strip(); category=request.form.get("category","Other")
    try: amount=float(request.form.get("amount","0"))
    except: amount=0
    if not label or amount<=0: flash("Enter an expense description and positive amount.")
    else:
        record("expenses",{"label":label,"category":category,"amount":amount,"supplier":request.form.get("supplier","").strip(),"notes":request.form.get("notes","").strip(),"created_at":now()})
        flash("Expense saved." if db is not None else "Expense could not persist: configure MongoDB and redeploy.")
    return redirect(url_for("admin_home")+"#expenses")

@app.post("/admin/settings")
@admin_required
def save_settings():
    phone=re.sub(r"[^0-9+ ]","",request.form.get("phone",PHONE))[:24]
    location=request.form.get("location",LOCATION).strip()[:160]
    otp=request.form.get("otp_enabled")=="on"
    set_setting("admin_phone",phone); set_setting("location",location); set_setting("purchase_email_otp_enabled",otp)
    flash("Settings saved." if db is not None else "Settings saved for this session only. Configure MongoDB for persistence.")
    return redirect(url_for("admin_home")+"#settings")

@app.post("/admin/email")
@admin_required
def admin_email():
    recipients=list(dict.fromkeys(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",request.form.get("recipients",""))))
    subject=request.form.get("subject","").strip()[:180]; body=request.form.get("body","").strip()[:10000]
    if not recipients or not subject or not body: flash("Enter recipient email(s), subject and message.")
    else:
        sent=0
        for recipient in recipients:
            try: sent+=bool(send_email(recipient,subject,body))
            except Exception: app.logger.exception("Email send failed")
        record("campaigns",{"recipients":recipients,"subject":subject,"body":body,"sent_count":sent,"created_at":now()})
        flash(f"Email sent to {sent} of {len(recipients)} recipients." if sent else "No email sent. Check SMTP credentials.")
    return redirect(url_for("admin_home")+"#communications")

@app.get("/admin/export/<kind>")
@admin_required
def export_data(kind):
    import csv, io
    allowed={"orders":"orders","expenses":"expenses","visitors":"visitors","payments":"payments"}
    if kind not in allowed: abort(404)
    data=rows(allowed[kind],5000); output=__import__("io").StringIO()
    fields=sorted({k for d in data for k in d if k!="_id"})
    writer=csv.DictWriter(output,fieldnames=fields or ["empty"],extrasaction="ignore"); writer.writeheader()
    for d in data:
        for k,v in list(d.items()):
            if isinstance(v,(dict,list)): d[k]=str(v)
        writer.writerow(d)
    response=make_response(output.getvalue()); response.headers["Content-Type"]="text/csv; charset=utf-8"
    response.headers["Content-Disposition"]=f"attachment; filename=kimathi-{kind}.csv"
    return response

@app.get("/health")
def health(): return jsonify(status="ok",database="connected" if db is not None else "not_configured")

@app.errorhandler(404)
def not_found(e): return render_template("error.html",code=404,message="We couldn't find that page."),404
@app.errorhandler(500)
def server_error(e): return render_template("error.html",code=500,message="Something went wrong. Please try again."),500

if __name__=="__main__": app.run(debug=os.getenv("FLASK_DEBUG","false")=="true",port=int(os.getenv("PORT","5000")))
