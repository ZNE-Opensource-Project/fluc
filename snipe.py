from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import requests
import time
import threading

app = FastAPI()

PASSWORD = "urnUIT4rR"
found = False
current_username = None

_proxies = [
    "http://3tin3ehX:svBHNNaL@lite.flashproxy.io:6969"
]


def get_proxy():
    i = 0
    while True:
        yield _proxies[i % len(_proxies)]
        i += 1


def checker(username):
    global found

    proxy_gen = get_proxy()

    while not found:
        proxy = next(proxy_gen)

        proxies = {
            "http": proxy,
            "https": proxy
        }

        try:
            r = requests.post(
                "https://discord.com/api/unique-username/username-attempt-unauthed",
                json={"username": username},
                proxies=proxies,
                timeout=10
            )

            data = r.json()

            if not data["taken"]:
                found = True
                break

        except:
            pass

        time.sleep(1)


@app.get("/login-sniperist", response_class=HTMLResponse)
async def login_page():
    return """
    <h2>Login</h2>
    <form method="POST">
    <input type="password" name="password"/>
    <button>Enter</button>
    </form>
    """


@app.post("/login-sniperist")
async def login(password: str = Form(...)):
    if password == PASSWORD:
        return RedirectResponse(
            url="/super-secret-012397830254-asd-panel",
            status_code=302
        )
    return HTMLResponse("<h3>Wrong password</h3>")


@app.get("/super-secret-012397830254-asd-panel", response_class=HTMLResponse)
async def panel():
    return """
<html>

<h2>Username Checker</h2>

<button id="enableBtn">Enable Notifications</button>

<form method="POST">
<input name="username" placeholder="username">
<button>Start</button>
</form>

<script>

let notificationsReady = false;

// Ask permission ONLY after user click
document.getElementById("enableBtn").onclick = async () => {

    let perm = await Notification.requestPermission();

    if (perm === "granted") {
        notificationsReady = true;
        alert("Notifications enabled");
    } else {
        alert("You must allow notifications");
    }

};


const evt = new EventSource("/events-asdjpasidof2134");

evt.onmessage = function(event) {

    if(event.data === "found"){

        if(Notification.permission === "granted"){

            for(let i=0;i<5;i++){
                new Notification("Username Available!",{
                    body: "The username is now free",
                    icon: "https://cdn-icons-png.flaticon.com/512/1827/1827504.png"
                });
            }

        }

        alert("USERNAME AVAILABLE");
    }

};

</script>

</html>
"""

@app.get("/sw.js")
async def service_worker():
    return HTMLResponse("""
self.addEventListener('notificationclick', function(event) {
    event.notification.close();

    event.waitUntil(
        clients.openWindow('/')
    );
});
""", media_type="application/javascript")


@app.post("/super-secret-012397830254-asd-panel")
async def start_checker(username: str = Form(...)):
    global current_username, found

    current_username = username
    found = False

    threading.Thread(
        target=checker,
        args=(current_username,),
        daemon=True
    ).start()

    return RedirectResponse(
        url="/super-secret-012397830254-asd-panel",
        status_code=302
    )


@app.get("/events-asdjpasidof2134")
async def events():

    async def stream():
        global found

        while True:
            if found:
                yield "data: found\n\n"
                break

            await asyncio.sleep(1)

    import asyncio
    return StreamingResponse(stream(), media_type="text/event-stream")