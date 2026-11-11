from io import BytesIO
from pathlib import Path
import socket
import sys
import threading
import webbrowser

from flask import Flask, jsonify, redirect, url_for, render_template, request, send_file
from werkzeug.serving import BaseWSGIServer

from species_quiz.excel_loader import WorkbookError, load_species
from species_quiz.quiz import Quiz, QuizError


BUNDLE_ROOT = Path(__file__).resolve().parent
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else BUNDLE_ROOT


BANKS = {
    "Plants 8": "8年级植物",
    "Birds&Mammals 5-8": "8年级鸟类和哺乳动物",
    "Birds&Mammals 5-9": "9年级鸟类和哺乳动物",
}


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
    quiz = Quiz(questions) if questions is not None else None
    bank_title = BANKS["Plants 8"] if quiz else None
    images = {(q.row_number, i): image for q in (questions or []) for i, image in enumerate(q.images)}

    @app.get("/")
    def index():
        with lock:
            if quiz is None:
                return render_template("select.html", banks=BANKS)
            return render_template("quiz.html", bank_title=bank_title)

    @app.get("/mode")
    def select_mode():
        sheet = request.args.get("bank")
        if sheet not in BANKS:
            return "题库不存在", 400
        with lock:
            if quiz is not None:
                return redirect(url_for("index"))
        return render_template("mode.html", sheet=sheet, bank_title=BANKS[sheet])

    @app.post("/select")
    def select_bank():
        nonlocal quiz, bank_title, images
        sheet = request.form.get("bank")
        mode = request.form.get("mode")
        if sheet not in BANKS:
            return "题库不存在", 400
        if mode not in ("review", "test"):
            return "请选择复习或测试", 400
        with lock:
            if quiz is not None:
                return redirect(url_for("index"), code=303)
            try:
                bank = load_species(workbook_path or ROOT / "species.xlsx", sheet)
            except WorkbookError as exc:
                return render_template("error.html", error=str(exc), bank_title=BANKS[sheet]), 503
            quiz = Quiz(bank, mode=mode)
            bank_title = BANKS[sheet]
            images = {(q.row_number, i): image for q in bank for i, image in enumerate(q.images)}
        return redirect(url_for("index"), code=303)

    @app.get("/api/state")
    def state():
        with lock:
            if quiz is None:
                return jsonify(error="请先选择题库。"), 409
            return jsonify(quiz.state() | {"bank_title": bank_title})

    @app.post("/api/<action>")
    def action(action):
        nonlocal quiz, bank_title, images
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="请求格式不正确，请刷新页面。"), 400
        with lock:
            if quiz is None:
                return jsonify(error="请先选择题库。"), 409
            try:
                if action == "leave":
                    if payload.get("round_id") != quiz.round_id:
                        raise QuizError("本轮考试已更换，请刷新页面。")
                    quiz, bank_title, images = None, None, {}
                    return jsonify(status="SELECT_BANK")
                if action == "submit":
                    quiz.submit(payload.get("round_id"), payload.get("question_id"), payload.get("answer"))
                elif action == "next":
                    quiz.next(payload.get("round_id"), payload.get("question_id"))
                elif action == "previous":
                    quiz.previous(payload.get("round_id"), payload.get("question_id"))
                elif action == "restart":
                    quiz.restart(payload.get("round_id"))
                else:
                    return jsonify(error="操作不存在。"), 404
                return jsonify(quiz.state() | {"bank_title": bank_title})
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
        print("无法启动：端口 5000 可能已被占用。请关闭已运行的物种考试程序后重试。")
        return 1
    print("物种识别考试已启动：http://127.0.0.1:5000\n关闭此窗口或按 Ctrl+C 结束程序。")
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
