"use strict";

const $ = (id) => document.getElementById(id);
let state;
let busy = false;
const input = $("answer");
const preview = $("preview");

function imageGrid(urls, container) {
  container.replaceChildren();
  urls.forEach((url, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "image-button";
    button.setAttribute("aria-label", `放大图片 ${index + 1}`);
    const image = document.createElement("img");
    image.src = url;
    image.alt = `物种图片 ${index + 1}`;
    image.addEventListener("error", () => showError("图片加载失败，请刷新页面；若仍失败，请重新启动程序。"));
    button.append(image);
    button.addEventListener("click", () => {
      $("preview-image").src = url;
      preview.showModal();
    });
    container.append(button);
  });
}

function showError(message) {
  $("network-error").textContent = message;
  $("network-error").hidden = false;
}

function controls() {
  const locked = busy || !state || state.status !== "WAITING_FOR_ANSWER";
  input.disabled = locked;
  document.querySelectorAll("[data-character]").forEach((button) => { button.disabled = locked; });
  $("action").disabled = busy;
  $("restart").disabled = busy;
}

function render(previous) {
  $("loading").hidden = true;
  const finished = state.status === "FINISHED";
  $("quiz").hidden = finished;
  $("result").hidden = !finished;
  if (finished) {
    for (const key of ["total", "correct", "wrong"]) $(key).textContent = state[key];
    $("accuracy").textContent = `${state.accuracy}%`;
    $("perfect").hidden = state.wrong !== 0;
    $("mistakes").replaceChildren();
    state.mistakes.forEach((mistake, index) => {
      const card = document.createElement("article");
      card.className = "mistake";
      const title = document.createElement("h4");
      title.textContent = `错题 ${index + 1}`;
      const images = document.createElement("div");
      images.className = "image-grid";
      imageGrid(mistake.images, images);
      const answer = document.createElement("p");
      answer.className = "user-answer";
      answer.textContent = `你的答案：${mistake.answer.trim() ? mistake.answer : "未作答"}`;
      const correct = document.createElement("p");
      correct.textContent = `正确答案：${mistake.correct_answer}`;
      card.append(title, images, answer, correct);
      $("mistakes").append(card);
    });
  } else {
    $("progress").textContent = `${state.position} / ${state.total}`;
    $("progress-bar").style.width = `${state.position / state.total * 100}%`;
    const changed = !previous || previous.round_id !== state.round_id || previous.question_id !== state.question_id;
    if (changed) {
      imageGrid(state.images, $("question-images"));
      input.value = "";
    }
    const answered = state.status === "ANSWERED";
    $("feedback").hidden = !answered;
    $("action").textContent = answered ? (state.position === state.total ? "查看成绩" : "下一题") : "提交";
    if (answered) {
      input.value = state.answer;
      $("verdict").textContent = state.correct ? "✓ 正确" : "✗ 错误";
      $("feedback").classList.toggle("incorrect", !state.correct);
      $("correct-answer").textContent = state.correct_answer;
    }
  }
  controls();
}

async function requestState(action) {
  if (busy) return;
  busy = true;
  controls();
  $("network-error").hidden = true;
  try {
    const options = action ? {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({round_id: state.round_id, question_id: state.question_id, answer: input.value})
    } : {};
    const response = await fetch(action ? `/api/${action}` : "/api/state", options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "操作失败，请刷新页面后继续。");
    const previous = state;
    state = data;
    render(previous);
    if (action === "restart" || state.status === "FINISHED") window.scrollTo(0, 0);
  } catch (error) {
    showError(error.message === "Failed to fetch" ? "无法连接程序，请确认运行窗口仍然打开，再刷新页面。" : error.message);
  } finally {
    busy = false;
    controls();
    if (state?.status === "WAITING_FOR_ANSWER") input.focus();
    else if (state?.status === "ANSWERED") $("action").focus();
  }
}

function advance() {
  if (!state || busy || preview.open || state.status === "FINISHED") return;
  requestState(state.status === "WAITING_FOR_ANSWER" ? "submit" : "next");
}

$("action").addEventListener("click", advance);
$("restart").addEventListener("click", () => requestState("restart"));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.isComposing || event.keyCode === 229 || preview.open || state?.status === "FINISHED") return;
  event.preventDefault();
  if (!event.repeat) advance();
});
document.querySelectorAll("[data-character]").forEach((button) => {
  button.addEventListener("mousedown", (event) => event.preventDefault());
  button.addEventListener("click", () => {
    if (input.disabled) return;
    // Insert at the caret without deleting existing selected text.
    const start = input.selectionStart ?? input.value.length;
    input.setRangeText(button.dataset.character, start, start, "end");
    input.focus();
  });
});
$("close-preview").addEventListener("click", () => preview.close());
preview.addEventListener("click", (event) => { if (event.target === preview) preview.close(); });
requestState();
