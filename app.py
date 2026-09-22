from io import BytesIO
from pathlib import Path
import socket
import sys
import threading
import webbrowser

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.serving import BaseWSGIServer

from plant_quiz.excel_loader import WorkbookError, load_plants
from plant_quiz.quiz import Quiz, QuizError


BUNDLE_ROOT = Path(__file__).resolve().parent
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BUNDLE_ROOT


class LocalServer(BaseWSGIServer):
    # Windows SO_REUSEADDR can let a second process bind the same address.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_app(workbook_path=None, questions=None):
    app = Flask(__name__, template_folder=str(BUNDLE_ROOT / "templates"),
                static_folder=str(BUNDLE_ROOT / "static"))
    lock = threading.Lock()
    error = None
    try:
        bank = questions if questions is not None else load_plants(workbook_path or ROOT / "plants.xlsx")
        quiz = Quiz(bank)
    except WorkbookError as exc:
        error = str(exc)
        app.logger.exception("题库加载失败")
        bank, quiz = [], None
    images = {(q.row_number, i): image for q in bank for i, image in enumerate(q.images)}

    @app.get("/")
    def index():
        if error:
            return render_template("error.html", error=error), 503
        return render_template("quiz.html")

    @app.get("/api/state")
    def state():
        if error:
            return jsonify(error=error), 503
        with lock:
            return jsonify(quiz.state())

    @app.post("/api/<action>")
    def action(action):
        if error:
            return jsonify(error=error), 503
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="请求格式不正确，请刷新页面。"), 400
        with lock:
            try:
                if action == "submit":
                    quiz.submit(payload.get("round_id"), payload.get("question_id"), payload.get("answer"))
                elif action == "next":
                    quiz.next(payload.get("round_id"), payload.get("question_id"))
                elif action == "restart":
                    quiz.restart(payload.get("round_id"))
                else:
                    return jsonify(error="操作不存在。"), 404
                return jsonify(quiz.state())
            except QuizError as exc:
                return jsonify(error=str(exc)), 409

    @app.get("/images/<int:row>/<int:number>")
    def image(row, number):
        item = images.get((row, number))
        if item is None:
            return "图片不存在", 404
        return send_file(BytesIO(item.data), mimetype=item.mime_type)

    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def main():
    app = create_app()
    try:
        server = LocalServer("127.0.0.1", 5000, app)
    except (OSError, SystemExit):
        print("无法启动：端口 5000 可能已被占用。请关闭已运行的植物考试程序后重试。")
        return 1
    print("植物识别考试已启动：http://127.0.0.1:5000\n关闭此窗口或按 Ctrl+C 结束程序。")
    # The listening socket is bound before opening the browser; no reloader.
    threading.Thread(target=webbrowser.open, args=("http://127.0.0.1:5000",), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
