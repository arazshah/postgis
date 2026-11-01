"""سرویس ساختگی سازگار با OpenAI برای ضبط ویدیوی دستیار (بدون شبکه): embedding ثابت و پاسخ فارسی با ارجاع [۱]."""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = ("بکاپ کامل هر شب حدود ساعت ۳ بامداد گرفته می‌شود و بسته به پلن چند روز تا یک ماه نگه داشته می‌شود [1]. "
          "بکاپ دستی را هم می‌توانید پیش از هر تغییر بزرگ بگیرید؛ آن ۷ روز می‌ماند [1].")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            texts = body.get("input", [])
            data = [{"index": i, "embedding": [b / 255 for b in hashlib.sha256(t.encode()).digest()[:16]]} for i, t in enumerate(texts)]
            out = json.dumps({"data": data}).encode()
            self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers()
            self.wfile.write(out)
            return
        if body.get("stream"):
            self.send_response(200), self.send_header("Content-Type", "text/event-stream"), self.end_headers()
            words = ANSWER.split(" ")
            for i in range(0, len(words), 3):
                piece = " ".join(words[i:i + 3]) + " "
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        out = json.dumps({"choices": [{"message": {"content": ANSWER}}]}, ensure_ascii=False).encode()
        self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers()
        self.wfile.write(out)


def start(port=8899):
    import threading

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
