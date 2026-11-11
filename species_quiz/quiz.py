import random
from uuid import uuid4


class QuizError(ValueError):
    pass


class Quiz:
    def __init__(self, questions, mode="test"):
        self.questions = questions
        self.mode = mode
        self._start()

    def _start(self):
        self.round_id = uuid4().hex
        self.order = list(self.questions)
        random.shuffle(self.order)
        self.position = 0
        self.answers = []

    @property
    def finished(self):
        return self.position == len(self.order)

    @property
    def answered(self):
        return len(self.answers) > self.position

    def _check(self, round_id, question_id):
        if self.finished or round_id != self.round_id or question_id != self.order[self.position].row_number:
            raise QuizError("题目状态已变化，请刷新页面后继续。")

    def submit(self, round_id, question_id, answer):
        self._check(round_id, question_id)
        if self.mode == "review":
            raise QuizError("复习模式无需提交答案。")
        if self.answered:
            raise QuizError("本题已经提交，不能重复作答。")
        if not isinstance(answer, str):
            raise QuizError("答案必须为文字。")
        expected = self.order[self.position].name
        correct = bool(answer.strip()) and answer.strip().casefold() == expected.strip().casefold()
        self.answers.append({"answer": answer, "correct": correct})

    def next(self, round_id, question_id):
        self._check(round_id, question_id)
        if self.mode == "test" and not self.answered:
            raise QuizError("请先提交本题答案。")
        self.position += 1

    def previous(self, round_id, question_id):
        self._check(round_id, question_id)
        if self.mode != "review" or self.position == 0:
            raise QuizError("当前没有可返回的复习题目。")
        self.position -= 1

    def restart(self, round_id):
        if not self.finished or round_id != self.round_id:
            raise QuizError("只有完成本轮考试后才能重新开始。")
        self._start()

    @staticmethod
    def image_urls(question):
        return [f"/images/{question.row_number}/{i}" for i in range(len(question.images))]

    def state(self):
        state = {"round_id": self.round_id, "total": len(self.order), "mode": self.mode}
        if self.mode == "review":
            if self.finished:
                return state | {"status": "FINISHED"}
            question = self.order[self.position]
            return state | {"status": "REVIEW", "question_id": question.row_number,
                            "position": self.position + 1, "images": self.image_urls(question),
                            "correct_answer": question.name}
        if self.finished:
            correct = sum(answer["correct"] for answer in self.answers)
            state.update(status="FINISHED", correct=correct, wrong=len(self.order) - correct,
                         accuracy=round(correct / len(self.order) * 100, 1),
                         mistakes=[{"images": self.image_urls(question), "answer": answer["answer"],
                                    "correct_answer": question.name}
                                   for question, answer in zip(self.order, self.answers) if not answer["correct"]])
        else:
            question = self.order[self.position]
            state.update(status="ANSWERED" if self.answered else "WAITING_FOR_ANSWER",
                         question_id=question.row_number, position=self.position + 1,
                         images=self.image_urls(question))
            if self.answered:
                state.update(self.answers[self.position], correct_answer=question.name)
        return state
