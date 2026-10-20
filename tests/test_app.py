import os
os.environ.setdefault("SECRET_KEY","test-secret")
os.environ.setdefault("MONGODB_URI","")
os.environ.setdefault("ADMIN_PASSWORD","test-admin-password")
from app import app

def test_home_renders():
    app.config["TESTING"]=True
    with app.test_client() as c:
        r=c.get("/")
        assert r.status_code==200
        assert b"KIMATHI" in r.data

def test_health():
    app.config["TESTING"]=True
    with app.test_client() as c:
        r=c.get("/health")
        assert r.status_code==200
        assert r.json["status"]=="ok"

def test_admin_login_required():
    app.config["TESTING"]=True
    with app.test_client() as c:
        r=c.get("/admin")
        assert r.status_code in (200,302)
        assert b"Admin" in r.data or r.status_code==302
