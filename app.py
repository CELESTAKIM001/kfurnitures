import os, re, secrets, smtplib, base64, datetime, hashlib, mimetypes, uuid
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, make_response
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as PDFImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
import qrcode

load_dotenv()
app = Flask(__name__, static_folder="static", template_folder="templates")
_secret_key=os.getenv("SECRET_KEY","").strip()
if os.getenv("VERCEL") and not _secret_key:
    raise RuntimeError("SECRET_KEY must be configured in Vercel Environment Variables before production use.")
app.secret_key = _secret_key or "local-development-only-change-this-secret"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE","true").lower()=="true",
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE","Lax"),
    MAX_CONTENT_LENGTH=4*1024*1024
)
COMPANY = os.getenv("COMPANY_NAME","KIMATHI Furniture")
PHONE = os.getenv("ADMIN_PHONE","0702781490")
LOCATION = os.getenv("DEFAULT_LOCATION","Kimathi, Nyeri")
# Keep the admin console off the public navigation and move it to a configurable path.
# Set ADMIN_PATH in Vercel to a private, hard-to-guess path (including the leading slash).
ADMIN_BASE_PATH = os.getenv("ADMIN_PATH", "/private-office-console").strip() or "/private-office-console"
if not ADMIN_BASE_PATH.startswith("/"):
    ADMIN_BASE_PATH = "/" + ADMIN_BASE_PATH
ADMIN_BASE_PATH = re.sub(r"[^/A-Za-z0-9_-]", "", ADMIN_BASE_PATH).rstrip("/") or "/private-office-console"
PRODUCTS = [
 {"name":"Armed Office Chair","price":12500,"category":"Seating","image":"armed-officechair.webp","description":"Comfort-led seating for focused work."},
 {"name":"Bedroom Collection","price":42000,"category":"Bedroom","image":"bed.webp","description":"A calmer foundation for your space."},
 {"name":"Work Desk","price":18500,"category":"Office","image":"desks.webp","description":"Clean lines for a considered workspace."},
 {"name":"Dining Table","price":35000,"category":"Dining","image":"landing-dining.webp","description":"Gather around timeless craftsmanship."},
 {"name":"Living Room Set","price":68000,"category":"Living","image":"landing2-nicetableroom.webp","description":"Thoughtful comfort for everyday living."},
 {"name":"Wood Frame Mirrors","price":8500,"category":"Decor","image":"mirrors-wood-designframes.webp","description":"Warm natural texture and useful detail."},
 {"name":"Furniture Set","price":55000,"category":"Living","image":"nice-furnitures.webp","description":"Versatile pieces for modern homes."},
 {"name":"Premium Furniture","price":48000,"category":"Living","image":"nice2-fur.webp","description":"Designed to live beautifully."},
 {"name":"Home Essentials","price":22000,"category":"Living","image":"other-furnitures.webp","description":"Finishing touches for your home."},
 {"name":"Reception Desk","price":39000,"category":"Office","image":"reception-desk.webp","description":"Make a confident first impression."},
 {"name":"Wooden Serving Plates","price":2800,"category":"Decor","image":"wooden-plates.webp","description":"Natural wood for everyday hosting."}
]
for _i, _product in enumerate(PRODUCTS):
    _product["product_id"] = "seed-" + str(_i)
    _product.setdefault("stock", 10)
    _product.setdefault("published", True)
    _product.setdefault("sku", "KF-%04d" % (_i + 1))
client = db = None
try:
    uri = os.getenv("MONGODB_URI","").strip()
    if uri and "REPLACE_PASSWORD" not in uri and "<" not in uri:
        client = MongoClient(uri, serverSelectionTimeoutMS=2500, connectTimeoutMS=2500)
        db = client[os.getenv("MONGODB_DB","kimathi_furniture")]
except Exception:
    client = db = None

def now(): return datetime.datetime.now(datetime.timezone.utc)

def catalog(include_unpublished=False):
    """Return database products plus the curated seed catalogue when no custom products exist."""
    c=coll("products")
    merged={p["product_id"]:dict(p) for p in PRODUCTS}
    if c is not None:
        try:
            for item in c.find({}, {"_id":0}).sort("created_at", DESCENDING):
                if item.get("product_id"): merged[item["product_id"]]=item
        except Exception: app.logger.exception("Could not load products")
    return [x for x in merged.values() if include_unpublished or x.get("published", True)]

def product_by_id(product_id):
    for item in catalog():
        if str(item.get("product_id")) == str(product_id): return item
    # compatibility for old links and cart sessions using catalogue indexes
    if str(product_id).isdigit():
        items=catalog()
        idx=int(product_id)
        if 0 <= idx < len(items): return items[idx]
    return None

def product_image(p):
    return p.get("image_data") or (url_for("static", filename="images/"+p.get("image", "nice-furnitures.webp")) if p.get("image") else url_for("static",filename="images/nice-furnitures.webp"))

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
    if request.path.startswith("/static/") or request.path.startswith("/api/") or request.path.startswith(ADMIN_BASE_PATH) or request.path.startswith("/admin"): return
    try: record("visitors",{"path":request.path,"referrer":request.referrer or "direct","user_agent":request.user_agent.string[:250],"ip_hash":hashlib.sha256((request.remote_addr or "").encode()).hexdigest()[:16],"at":now()})
    except Exception: pass

@app.after_request
def protect_admin_indexing(response):
    if request.path.startswith(ADMIN_BASE_PATH) or request.path.startswith("/admin"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["Cache-Control"] = "no-store, private"
    return response

@app.context_processor
def globals_for_templates():
    return {"company":COMPANY,"phone":get_setting("admin_phone",PHONE),"location":get_setting("location",LOCATION),"cart_count":len(session.get("cart",[]))}

@app.route("/")
def home():
    return render_template("home.html", products=catalog(), videos=["kimathi_furniture_premium_logo_ad.mp4","kimathi_furniture_logo_reveal.mp4"], image_for=product_image)

@app.route("/product/<slug>")
def product(slug):
    p=product_by_id(slug)
    if not p: abort(404)
    return render_template("product.html",p=p,idx=p.get("product_id",slug),image_for=product_image)

@app.post("/cart/add")
def cart_add():
    i=request.form.get("product_id",""); p=product_by_id(i)
    if not p: return jsonify(ok=False,error="Product not found"),404
    if int(p.get("stock",1) or 0) < 1: return jsonify(ok=False,error="This item is currently out of stock"),409
    cart=session.get("cart",[]); cart.append(str(p.get("product_id",i))); session["cart"]=cart
    return jsonify(ok=True,count=len(cart))

@app.get("/cart")
def cart():
    items=[]
    for product_id in session.get("cart",[]):
        p=product_by_id(product_id)
        if p: items.append({**p,"idx":product_id})
    return render_template("cart.html",items=items,total=sum(float(p["price"]) for p in items),image_for=product_image)

@app.post("/cart/remove")
def cart_remove():
    cart=session.get("cart",[])
    try: idx=int(request.form.get("index","-1"))
    except: idx=-1
    if 0<=idx<len(cart): cart.pop(idx); session["cart"]=cart
    return redirect(url_for("cart"))

@app.route("/checkout",methods=["GET","POST"])
def checkout():
    items=[{"idx":pid,**p} for pid in session.get("cart",[]) if (p:=product_by_id(pid))]
    if not items: flash("Your bag is empty."); return redirect(url_for("home"))
    if request.method=="POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip().lower()
        phone=request.form.get("phone","").strip(); delivery=request.form.get("delivery","").strip()
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or not phone:
            flash("Enter your name, valid email and phone number."); return redirect(url_for("checkout"))
        order_id=secrets.token_hex(5).upper()
        total=sum(p["price"] for p in items)
        order={"order_id":order_id,"customer_name":name,"email":email,"phone":phone,"delivery_address":delivery,"items":[{"product_id":p.get("product_id"),"name":p["name"],"price":p["price"],"image":p.get("image","nice-furnitures.webp"),"quantity":1} for p in items],"amount":total,"status":"Pending payment","payment_status":"unpaid","created_at":now()}
        record("orders",order)
        session["cart"]=[]
        if get_setting("purchase_email_otp_enabled",os.getenv("PURCHASE_EMAIL_OTP_ENABLED","false").lower()=="true"):
            code=f"{secrets.randbelow(1000000):06d}"
            session["checkout_otp"]={"order_id":order_id,"email":email,"hash":hashlib.sha256(code.encode()).hexdigest(),"expires":(now()+datetime.timedelta(minutes=10)).timestamp()}
            try: send_email(email,f"{COMPANY} email verification",f"Your verification code is {code}. It expires in 10 minutes.")
            except Exception: pass
            return redirect(url_for("verify_email"))
        return redirect(url_for("payment",order_id=order_id))
    customer_prefill={"name":session.get("customer_name", ""),"email":session.get("customer_email", ""),"phone":""}
    if session.get("customer_email") and coll("customers") is not None:
        try:
            saved=coll("customers").find_one({"email":session["customer_email"]}) or {}
            customer_prefill.update({"name":saved.get("name",customer_prefill["name"]),"phone":saved.get("phone","")})
        except Exception: pass
    return render_template("checkout.html",items=items,total=sum(p["price"] for p in items),image_for=product_image,customer=customer_prefill)

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
    if not key or not secret: raise ValueError("Daraja credentials missing: set MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET in Vercel.")
    auth=base64.b64encode(f"{key}:{secret}".encode()).decode()
    base=os.getenv("DARAJA_BASE_URL","https://api.safaricom.co.ke").rstrip("/")
    r=requests.get(base+"/oauth/v1/generate?grant_type=client_credentials",headers={"Authorization":"Basic "+auth},timeout=15)
    if not r.ok:
        app.logger.error("Daraja OAuth rejected credentials: HTTP %s; response=%s",r.status_code,r.text[:500])
        raise ValueError("Daraja OAuth failed (HTTP %s). Check the consumer key/secret and sandbox/production environment." % r.status_code)
    try: return r.json()["access_token"]
    except (ValueError,KeyError): raise ValueError("Daraja OAuth response did not include an access token.")

def resolve_mpesa_callback_url():
    """Resolve a public HTTPS callback URL; use the canonical deployed host if unset."""
    configured = os.getenv("MPESA_CALLBACK_URL", "").strip()
    public_base = (os.getenv("PUBLIC_APP_URL", "").strip() or os.getenv("FRONTEND_URL", "").strip()).rstrip("/")
    if not public_base:
        vercel_host = os.getenv("VERCEL_URL", "").strip()
        if vercel_host:
            public_base = "https://" + vercel_host
    candidate = configured or (public_base + "/api/mpesa/callback" if public_base else "")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid callback URL. Set MPESA_CALLBACK_URL to the public HTTPS URL https://YOUR-PRODUCTION-DOMAIN/api/mpesa/callback and ensure the deployment is publicly reachable.")
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "0.0.0.0"}:
        raise ValueError("M-Pesa callback must use a public hostname, not localhost or a private address.")
    if parsed.path.rstrip("/") != "/api/mpesa/callback" or parsed.query or parsed.fragment:
        raise ValueError("Set MPESA_CALLBACK_URL to the exact callback route: https://YOUR-PRODUCTION-DOMAIN/api/mpesa/callback (no query string or fragment).")
    return candidate

@app.post("/api/mpesa/stkpush")
def stkpush():
    data=request.get_json(silent=True) or request.form
    order_id=str(data.get("order_id",""))
    order=find_order(order_id)
    if not order: return jsonify(ok=False,error="Order not found"),404
    if order.get("payment_status")=="paid": return jsonify(ok=True,message="This order is already marked paid. Do not retry payment.",already_paid=True),200
    phone=re.sub(r"\D","",str(data.get("phone") or order.get("phone","")))
    if phone.startswith("0"): phone="254"+phone[1:]
    if phone.startswith("+"): phone=phone[1:]
    if not re.fullmatch(r"254[17]\d{8}",phone): return jsonify(ok=False,error="Use a valid Kenyan M-Pesa number, e.g. 0712345678."),400
    shortcode=os.getenv("MPESA_BUSINESS_SHORT_CODE","").strip()
    till=os.getenv("MPESA_VENDOR_TILL","").strip()
    passkey=os.getenv("MPESA_PASSKEY","").strip()
    try:
        callback=resolve_mpesa_callback_url()
    except ValueError as exc:
        return jsonify(ok=False,error=str(exc)),503
    if not all([shortcode,passkey]):
        return jsonify(ok=False,error="M-Pesa setup incomplete. Set MPESA_BUSINESS_SHORT_CODE and MPESA_PASSKEY in Vercel."),503
    transaction_type=os.getenv("MPESA_TRANSACTION_TYPE","CustomerBuyGoodsOnline").strip()
    if transaction_type == "CustomerBuyGoodsOnline" and not till:
        return jsonify(ok=False,error="For Buy Goods, set MPESA_VENDOR_TILL (PartyB) to the approved till number."),503
    try:
        token=mpesa_token()
        stamp=now().astimezone(datetime.timezone(datetime.timedelta(hours=3))).strftime("%Y%m%d%H%M%S")
        password=base64.b64encode((shortcode+passkey+stamp).encode()).decode()
        amount=max(1,int(round(float(order["amount"]))))
        payload={"BusinessShortCode":shortcode,"Password":password,"Timestamp":stamp,"TransactionType":transaction_type,"Amount":amount,"PartyA":phone,"PartyB":(till or shortcode),"PhoneNumber":phone,"CallBackURL":callback,"AccountReference":order_id,"TransactionDesc":f"{COMPANY} order {order_id}"}
        base=os.getenv("DARAJA_BASE_URL","https://api.safaricom.co.ke").rstrip("/")
        res=requests.post(base+"/mpesa/stkpush/v1/processrequest",json=payload,headers={"Authorization":"Bearer "+token},timeout=25)
        try:
            body=res.json()
        except ValueError:
            body={"ResponseDescription":res.text[:500] or "Daraja returned a non-JSON response."}
        record("payments",{"order_id":order_id,"amount":amount,"phone":phone,"daraja_http_status":res.status_code,"callback_host":urlparse(callback).hostname,"request_payload":{k:v for k,v in body.items() if k not in ("Password",)},"created_at":now()})
        if res.ok and body.get("ResponseCode")=="0":
            c=coll("orders")
            if c is not None: c.update_one({"order_id":order_id},{"$set":{"checkout_request_id":body.get("CheckoutRequestID"),"merchant_request_id":body.get("MerchantRequestID"),"status":"STK prompt sent"}})
            return jsonify(ok=True,message="STK prompt requested. Check your phone and enter your M-Pesa PIN to authorize.",checkout_request_id=body.get("CheckoutRequestID"))
        app.logger.error("Daraja STK rejected request: HTTP %s; response=%s",res.status_code,str(body)[:800])
        reason=body.get("errorMessage") or body.get("ResponseDescription") or body.get("ResponseDesc") or "Safaricom did not accept the STK request."
        return jsonify(ok=False,error=str(reason),hint="Check Daraja environment, shortcode, transaction type, passkey, till configuration and callback URL."),502
    except Exception as e:
        app.logger.exception("STK request failed")
        return jsonify(ok=False,error=str(e) if isinstance(e,ValueError) or app.debug else "Payment service is temporarily unavailable. Check server logs for the Daraja error.",hint="Confirm Vercel environment variables and redeploy after changing them."),502

@app.route("/api/mpesa/callback", methods=["GET", "POST"])
def mpesa_callback():
    if request.method == "GET":
        return jsonify(ok=True, service="mpesa-callback", message="Callback endpoint is reachable."), 200
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
                # Decrement stock once only, on the first successful callback.
                if order.get("payment_status") != "paid":
                    pc=coll("products")
                    for item in order.get("items",[]):
                        pid=item.get("product_id")
                        if not pid: continue
                        if pc is not None:
                            existing=pc.find_one({"product_id":pid})
                            if existing:
                                pc.update_one({"product_id":pid,"stock":{"$gt":0}},{"$inc":{"stock":-1}})
                            else:
                                seed=next((dict(x) for x in PRODUCTS if x.get("product_id")==pid),None)
                                if seed:
                                    seed["stock"]=max(0,int(seed.get("stock",10))-1); seed["created_at"]=now()
                                    pc.update_one({"product_id":pid},{"$set":seed},upsert=True)
            else:
                cancelled="cancel" in str(meta.get("ResultDesc","")).lower() or str(result_code)=="1032"
                updates.update({"payment_status":"cancelled" if cancelled else "failed","status":"Cancelled" if cancelled else "Payment failed"})
            c.update_one({"_id":order["_id"]},{"$set":updates})
            record("payments",{"order_id":order["order_id"],"callback":body,"result_code":result_code,"created_at":now()})
            # Notify the customer only after Safaricom's callback updates the authoritative order.
            try:
                if str(result_code)=="0":
                    send_email(order.get("email",""),f"{COMPANY} payment confirmed — {order['order_id']}",f"Hello {order.get('customer_name','Customer')}, your payment of KSh {float(order.get('amount',0)):,.2f} is confirmed. M-Pesa receipt: {metadata.get('MpesaReceiptNumber','pending')}. Download your receipt: {request.url_root.rstrip('/')}/receipt/{order['order_id']}/pdf\nValidate receipt: {request.url_root.rstrip('/')}/validate/{order['order_id']}")
                else:
                    send_email(order.get("email",""),f"{COMPANY} payment not completed — {order['order_id']}",f"Your M-Pesa payment was not completed ({meta.get('ResultDesc','cancelled or failed')}). No successful payment is recorded. You can retry securely here: {request.url_root.rstrip('/')}/payment/{order['order_id']}")
            except Exception: app.logger.exception("Payment notification email failed for order %s",order.get("order_id"))
    return jsonify(ResultCode=0,ResultDesc="Accepted")

@app.get("/receipt/<order_id>")
def receipt(order_id):
    order=find_order(order_id)
    if not order: abort(404)
    return render_template("receipt.html",order=order)

@app.route("/customer/login",methods=["GET","POST"])
def customer_login():
    if request.method=="POST":
        email=request.form.get("email"," ").strip().lower(); password=request.form.get("password","")
        c=coll("customers"); user=None
        if c is not None:
            try: user=c.find_one({"email":email})
            except Exception: app.logger.exception("Customer login lookup failed")
        if user and check_password_hash(user.get("password_hash",""),password):
            session["customer_email"]=email; session["customer_name"]=user.get("name",email); session.permanent=True
            return redirect(url_for("customer_account"))
        flash("Email or password was not recognised. If you are new, create an account.")
    return render_template("customer_auth.html",mode="login")

@app.route("/customer/register",methods=["GET","POST"])
def customer_register():
    if request.method=="POST":
        name=request.form.get("name","").strip()[:120]; email=request.form.get("email","").strip().lower(); phone=request.form.get("phone","").strip()[:30]; password=request.form.get("password","")
        if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email) or len(password)<10 or not phone:
            flash("Enter your name, valid email, phone number and a password of at least 10 characters.")
        else:
            c=coll("customers")
            if c is None: flash("Customer accounts need MongoDB configured before they can be saved securely.")
            else:
                try:
                    if c.find_one({"email":email}): flash("An account already exists for that email. Please sign in.")
                    else:
                        c.insert_one({"name":name,"email":email,"phone":phone,"password_hash":generate_password_hash(password),"created_at":now()})
                        session["customer_email"]=email; session["customer_name"]=name; session.permanent=True
                        try: send_email(email,f"Welcome to {COMPANY}",f"Hello {name}, your customer account is ready. You can track orders and check receipts after signing in.")
                        except Exception: app.logger.exception("Customer welcome email failed")
                        return redirect(url_for("customer_account"))
                except Exception: app.logger.exception("Customer registration failed"); flash("Account creation failed. Please try again.")
    return render_template("customer_auth.html",mode="register")

@app.get("/customer/account")
def customer_account():
    email=session.get("customer_email")
    if not email: return redirect(url_for("customer_login"))
    c=coll("orders"); orders=[]
    if c is not None:
        try: orders=list(c.find({"email":email},{"_id":0}).sort("created_at",DESCENDING).limit(100))
        except Exception: app.logger.exception("Customer order history lookup failed")
    return render_template("customer_account.html",orders=orders,name=session.get("customer_name",email))

@app.post("/customer/logout")
def customer_logout():
    session.pop("customer_email",None); session.pop("customer_name",None); return redirect(url_for("home"))

@app.get("/api/order-status/<order_id>")
def order_status(order_id):
    order=find_order(order_id)
    if not order: return jsonify(ok=False,error="Order not found"),404
    return jsonify(ok=True,payment_status=order.get("payment_status","unpaid"),status=order.get("status","Pending payment"),receipt=order.get("mpesa_receipt"))

@app.get("/validate/<order_id>")
def validate_receipt(order_id):
    order=find_order(order_id)
    if not order: return render_template("error.html",code=404,message="Receipt reference not found."),404
    return render_template("validate.html",order=order,valid=order.get("payment_status")=="paid" and bool(order.get("mpesa_receipt")))

@app.get("/receipt/<order_id>/pdf")
def receipt_pdf(order_id):
    """Generate a resilient, branded receipt PDF without trusting user text as markup."""
    order=find_order(order_id)
    if not order:
        return render_template("error.html",code=404,message="Receipt reference not found. Please check the order reference."),404
    try:
        buf=BytesIO()
        doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=16*mm,bottomMargin=18*mm)
        styles=getSampleStyleSheet()
        if "BrandGreen" not in styles:
            styles.add(ParagraphStyle(name="BrandGreen",parent=styles["Title"],textColor=colors.HexColor("#176b45"),fontSize=22,leading=27,spaceAfter=4))
        story=[]
        logo=os.path.join(app.static_folder,"images","mainlogo.png")
        if os.path.exists(logo):
            try: story.append(PDFImage(logo,width=42*mm,height=22*mm,kind="proportional")); story.append(Spacer(1,5*mm))
            except Exception: app.logger.exception("Receipt logo could not be embedded")
        order_ref=xml_escape(str(order.get("order_id",order_id)))
        customer=xml_escape(str(order.get("customer_name") or "Customer"))
        email=xml_escape(str(order.get("email") or "Not provided"))
        status=xml_escape(str(order.get("status") or "Pending payment"))
        payment_status=xml_escape(str(order.get("payment_status") or "unpaid").upper())
        story += [Paragraph("KIMATHI FURNITURE",styles["BrandGreen"]),Paragraph("Furniture for living. Thoughtfully selected for homes and workspaces.",styles["Normal"]),Spacer(1,8*mm),Paragraph("PAYMENT RECEIPT",styles["Heading1"]),Paragraph(f"Order reference: <b>{order_ref}</b>",styles["Normal"]),Paragraph(f"Customer: {customer}",styles["Normal"]),Paragraph(f"Email: {email}",styles["Normal"]),Paragraph(f"Order status: {status}",styles["Normal"]),Paragraph(f"Payment status: <b>{payment_status}</b>",styles["Normal"]),Spacer(1,5*mm)]
        data=[["Item","Qty","Unit price (KES)","Line total (KES)"]]
        for item in (order.get("items") or []):
            try:
                qty=max(1,int(item.get("quantity",1) or 1)); price=max(0.0,float(item.get("price",0) or 0))
            except (TypeError,ValueError): qty,price=1,0.0
            data.append([Paragraph(xml_escape(str(item.get("name") or "Item")),styles["Normal"]),str(qty),f"{price:,.2f}",f"{price*qty:,.2f}"])
        table=Table(data,colWidths=[76*mm,15*mm,35*mm,38*mm],repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#176b45")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d9e5dc")),("PADDING",(0,0),(-1,-1),8),("ALIGN",(1,1),(-1,-1),"RIGHT"),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("VALIGN",(0,0),(-1,-1),"TOP")]))
        try: amount=float(order.get("amount",0) or 0)
        except (TypeError,ValueError): amount=0.0
        mpesa=xml_escape(str(order.get("mpesa_receipt") or "Not yet confirmed"))
        story += [table,Spacer(1,5*mm),Paragraph(f"<b>Total: KSh {amount:,.2f}</b>",styles["Heading2"]),Paragraph(f"M-Pesa receipt: {mpesa}",styles["Normal"]),Spacer(1,6*mm)]
        verify_url=request.url_root.rstrip("/")+"/validate/"+order_ref
        qr=qrcode.QRCode(box_size=5,border=2); qr.add_data(verify_url); qr.make(fit=True)
        qrbuf=BytesIO(); qr.make_image(fill_color="#176b45",back_color="white").save(qrbuf,format="PNG"); qrbuf.seek(0)
        story += [PDFImage(qrbuf,width=31*mm,height=31*mm),Paragraph("Scan to validate this receipt online.",styles["Normal"]),Spacer(1,5*mm),Paragraph("This document confirms payment only when the online validation page shows VALID and a Safaricom M-Pesa receipt number is present.",styles["Italic"])]
        doc.build(story)
        response=make_response(buf.getvalue()); response.headers["Content-Type"]="application/pdf"; response.headers["Content-Disposition"]=f'attachment; filename="Kimathi-Receipt-{order_id}.pdf"'; response.headers["Cache-Control"]="no-store"; return response
    except Exception:
        app.logger.exception("Receipt PDF generation failed for order %s",order_id)
        return render_template("error.html",code=500,message="We could not generate this receipt right now. Your order record has not been changed. Please try again shortly or contact Kimathi Furniture with your order reference."),500

@app.get("/track/<order_id>")
def track(order_id):
    order=find_order(order_id)
    if not order:
        return render_template("error.html",code=404,message="We could not find that order reference. Check the reference on your payment page or receipt."),404
    # Public tracking deliberately excludes email, phone and address.
    try: amount=float(order.get("amount",0) or 0)
    except (TypeError,ValueError): amount=0.0
    safe_order={"order_id":str(order.get("order_id") or order_id),"status":str(order.get("status") or "Pending payment"),"payment_status":str(order.get("payment_status") or "unpaid"),"amount":amount,"created_at":order.get("created_at")}
    return render_template("track.html",order=safe_order)

@app.route(ADMIN_BASE_PATH, methods=["GET"])
def admin_home():
    if not session.get("is_admin"): return redirect(url_for("admin_login"))
    orders=rows("orders",100); expenses=rows("expenses",100); visitors=rows("visitors",100); products=catalog(include_unpublished=True)
    def number(value):
        try: return float(value or 0)
        except (TypeError, ValueError): return 0.0
    paid=sum(number(o.get("amount",0)) for o in orders if o.get("payment_status")=="paid")
    spent=sum(number(e.get("amount",0)) for e in expenses)
    today=now().date()
    def day_of(value):
        if isinstance(value,datetime.datetime): return value.date()
        if isinstance(value,str):
            try: return datetime.datetime.fromisoformat(value.replace("Z","+00:00")).date()
            except Exception: return None
        return None
    sales_today=sum(number(o.get("amount",0)) for o in orders if o.get("payment_status")=="paid" and day_of(o.get("paid_at") or o.get("created_at"))==today)
    expenses_today=sum(number(e.get("amount",0)) for e in expenses if day_of(e.get("created_at"))==today)
    daily_sales=[]
    for offset in range(6,-1,-1):
        d=today-datetime.timedelta(days=offset)
        amount=sum(number(o.get("amount",0)) for o in orders if o.get("payment_status")=="paid" and day_of(o.get("paid_at") or o.get("created_at"))==d)
        daily_sales.append({"label":d.strftime("%a"),"date":d.isoformat(),"amount":amount})
    return render_template("admin.html",orders=orders,expenses=expenses,visitors=visitors,paid=paid,spent=spent,sales_today=sales_today,expenses_today=expenses_today,daily_sales=daily_sales,products=products,db_ready=db is not None,modules={k:rows(k,100) for k in ["quotes","vendors","shipments","returns","swatches","service_jobs","documents","inventory_movements","trade_accounts","audit_log"]},gallery=["armed-officechair.webp","bed.webp","desks.webp","landing-dining.webp","landing2-nicetableroom.webp","mirrors-wood-designframes.webp","nice-furnitures.webp","nice2-fur.webp","other-furnitures.webp","reception-desk.webp","wooden-plates.webp"],otp_enabled=get_setting("purchase_email_otp_enabled",os.getenv("PURCHASE_EMAIL_OTP_ENABLED","false").lower()=="true"))

@app.route(ADMIN_BASE_PATH + "/login", methods=["GET", "POST"])
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

@app.post(ADMIN_BASE_PATH + "/logout")
@admin_required
def admin_logout():
    session.clear(); return redirect(url_for("home"))

@app.post(ADMIN_BASE_PATH + "/expense")
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

@app.post(ADMIN_BASE_PATH + "/settings")
@admin_required
def save_settings():
    phone=re.sub(r"[^0-9+ ]","",request.form.get("phone",PHONE))[:24]
    location=request.form.get("location",LOCATION).strip()[:160]
    otp=request.form.get("otp_enabled")=="on"
    set_setting("admin_phone",phone); set_setting("location",location); set_setting("purchase_email_otp_enabled",otp)
    flash("Settings saved." if db is not None else "Settings saved for this session only. Configure MongoDB for persistence.")
    return redirect(url_for("admin_home")+"#settings")

@app.post(ADMIN_BASE_PATH + "/email")
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

@app.post(ADMIN_BASE_PATH + "/products/save")
@admin_required
def admin_product_save():
    product_id=request.form.get("product_id","").strip() or "prod-"+uuid.uuid4().hex[:12]
    name=request.form.get("name","").strip()[:140]
    category=request.form.get("category","Living").strip()[:60]
    description=request.form.get("description","").strip()[:1200]
    sku=request.form.get("sku","").strip()[:80] or "KF-"+uuid.uuid4().hex[:8].upper()
    try: price=float(request.form.get("price","0")); stock=max(0,int(request.form.get("stock","0")))
    except ValueError: flash("Enter a valid price and stock quantity."); return redirect(url_for("admin_home")+"#catalogue")
    if not name or price<=0: flash("Product name and a positive KES price are required."); return redirect(url_for("admin_home")+"#catalogue")
    doc={"product_id":product_id,"name":name,"category":category,"description":description,"sku":sku,"price":round(price,2),"stock":stock,"published":request.form.get("published")=="on","updated_at":now()}
    image=request.files.get("image")
    if image and image.filename:
        safe=secure_filename(image.filename)
        mime=image.mimetype or mimetypes.guess_type(safe)[0] or ""
        raw=image.read(2*1024*1024+1)
        if mime not in ("image/jpeg","image/png","image/webp","image/gif") or len(raw)>2*1024*1024:
            flash("Upload a JPG, PNG, WEBP or GIF image up to 2 MB."); return redirect(url_for("admin_home")+"#catalogue")
        # Basic signature check prevents extension/MIME-only spoofing.
        valid=(raw.startswith(b"\xff\xd8\xff") if mime=="image/jpeg" else raw.startswith(b"\x89PNG\r\n\x1a\n") if mime=="image/png" else (raw[:4]==b"RIFF" and raw[8:12]==b"WEBP") if mime=="image/webp" else raw.startswith((b"GIF87a",b"GIF89a")))
        if not valid: flash("The uploaded file does not match its image type."); return redirect(url_for("admin_home")+"#catalogue")
        # Accept PNG/JPEG/WEBP/GIF uploads but normalize stored product images to optimized WEBP.
        try:
            from PIL import Image as PILImage
            im=PILImage.open(BytesIO(raw)).convert("RGB")
            converted=BytesIO(); im.save(converted,format="WEBP",quality=82,method=6)
            raw=converted.getvalue(); mime="image/webp"
        except Exception:
            if mime != "image/webp":
                flash("Image conversion failed. Please upload a valid PNG, JPG or WEBP image."); return redirect(url_for("admin_home")+"#catalogue")
        doc["image_data"]="data:image/webp;base64,"+base64.b64encode(raw).decode("ascii")
        doc["image"]=""
    else:
        fallback=request.form.get("fallback_image","").strip()
        allowed={x for x in os.listdir(os.path.join(app.static_folder,"images")) if x.lower().endswith((".png",".jpg",".jpeg",".webp"))}
        if fallback in allowed: doc["image"]=fallback
    c=coll("products")
    if c is None:
        flash("MongoDB is required to save products permanently. Configure MONGODB_URI in Vercel."); return redirect(url_for("admin_home")+"#catalogue")
    try:
        existing=c.find_one({"product_id":product_id})
        if existing:
            event="product_updated"
            if "image_data" not in doc and existing.get("image_data"): doc["image_data"]=existing["image_data"]
            if not doc.get("image") and existing.get("image"): doc["image"]=existing["image"]
        elif product_id.startswith("seed-"):
            seed=next((x for x in PRODUCTS if x.get("product_id")==product_id),None)
            if seed and not doc.get("image"): doc["image"]=seed.get("image", "nice-furnitures.webp")
            c.update_one({"product_id":product_id},{"$set":doc})
            event="product_updated"
        else:
            doc["created_at"]=now(); c.insert_one(doc); event="product_created"
        record("audit_log",{"event":event,"product_id":product_id,"sku":sku,"admin":"session"})
        flash("Product saved to the catalogue.")
    except Exception: app.logger.exception("Product save failed"); flash("Product could not be saved. Check MongoDB connection and logs.")
    return redirect(url_for("admin_home")+"#catalogue")

@app.post(ADMIN_BASE_PATH + "/products/delete")
@admin_required
def admin_product_delete():
    product_id=request.form.get("product_id","")
    c=coll("products")
    if c is None: flash("MongoDB must be configured to remove products.")
    else:
        result=c.delete_one({"product_id":product_id})
        record("audit_log",{"event":"product_deleted","product_id":product_id})
        flash("Product removed." if result.deleted_count else "Product not found in custom catalogue. Seed gallery items cannot be deleted.")
    return redirect(url_for("admin_home")+"#catalogue")

@app.post(ADMIN_BASE_PATH + "/order/update")
@admin_required
def admin_order_update():
    order_id=request.form.get("order_id",""); status=request.form.get("status","Processing")
    allowed={"Pending payment","Paid","Processing","In production","Ready for dispatch","Out for delivery","Delivered","Cancelled","Return requested","Payment failed"}
    if status not in allowed: abort(400)
    c=coll("orders")
    if c is not None:
        c.update_one({"order_id":order_id},{"$set":{"status":status,"updated_at":now()}})
        record("audit_log",{"event":"order_status_changed","order_id":order_id,"status":status})
        flash("Order status updated.")
    else: flash("Configure MongoDB before updating orders.")
    return redirect(url_for("admin_home")+"#orders")

@app.post(ADMIN_BASE_PATH + "/module/<module_name>")
@admin_required
def admin_module_add(module_name):
    allowed={"quotes","vendors","shipments","returns","swatches","service_jobs","documents","inventory_movements","trade_accounts"}
    if module_name not in allowed: abort(404)
    title=request.form.get("title","").strip()[:180]
    if not title: flash("A title or reference is required."); return redirect(url_for("admin_home")+"#operations")
    record(module_name,{"title":title,"reference":request.form.get("reference","").strip()[:120],"customer":request.form.get("customer","").strip()[:160],"amount":float(request.form.get("amount",0) or 0),"status":request.form.get("status","Open")[:80],"notes":request.form.get("notes","").strip()[:2000]})
    record("audit_log",{"event":"module_record_created","module":module_name,"title":title})
    flash("Record saved." if db is not None else "MongoDB is required for persistent operational records.")
    return redirect(url_for("admin_home")+"#operations")

@app.get(ADMIN_BASE_PATH + "/export/<kind>")
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
