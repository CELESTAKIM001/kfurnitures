import os
os.environ.setdefault("SECRET_KEY","test-secret")
os.environ.setdefault("MONGODB_URI","")
os.environ.setdefault("ADMIN_PASSWORD","test-admin-password")
from app import app, ADMIN_BASE_PATH

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

def test_admin_route_is_not_publicly_linked():
    app.config["TESTING"]=True
    with app.test_client() as c:
        old=c.get("/admin")
        assert old.status_code == 404
        login=c.get(ADMIN_BASE_PATH + "/login")
        assert login.status_code == 200
        assert b"Admin sign in" in login.data

def test_mpesa_callback_health_check():
    app.config["TESTING"]=True
    with app.test_client() as c:
        r=c.get("/api/mpesa/callback")
        assert r.status_code == 200
        assert r.json["ok"] is True
