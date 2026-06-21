(() => {
  const directExecute = document.getElementById("direct-execute");
  const mode = document.getElementById("mode");
  const confirmation = document.getElementById("execution-confirmation");
  const submit = document.getElementById("primary-submit");
  const actionNote = document.querySelector(".action-note");

  function updateExecutionMode() {
    if (!directExecute || !mode) return;
    const execute = directExecute.checked;
    mode.value = execute ? "execute" : "dry-run";
    confirmation?.classList.toggle("visible", execute);
    if (submit) {
      submit.textContent = execute ? "바로 생성하기" : "계획 확인하기";
    }
    if (actionNote) {
      actionNote.textContent = execute
        ? "승인 후 실제 파일을 생성합니다."
        : "파일이나 클러스터를 변경하지 않습니다.";
    }
  }
  directExecute?.addEventListener("change", updateExecutionMode);
  updateExecutionMode();

  const panel = document.getElementById("job-panel");
  if (panel) {
    const jobId = panel.dataset.jobId;
    const state = document.getElementById("job-state");
    const phase = document.getElementById("job-phase");
    const title = document.getElementById("job-title");
    const progress = document.getElementById("progress-fill");
    const stdout = document.getElementById("job-stdout");
    const stderr = document.getElementById("job-stderr");
    const cancel = document.getElementById("cancel-job");

    const phaseInfo = {
      queued: [5, "작업을 시작할 준비를 하고 있습니다."],
      starting: [10, "Agent를 시작하고 있습니다."],
      "LLM planning": [20, "요구사항을 이해하고 계획을 만들고 있습니다."],
      "LLM planning completed": [30, "계획을 확인했습니다."],
      "spec generation": [42, "Operator 구조를 정리하고 있습니다."],
      "command planning": [50, "안전한 실행 순서를 만들고 있습니다."],
      scaffold: [62, "Kubebuilder 프로젝트를 생성하고 있습니다."],
      "artifact patch": [72, "Controller 코드를 요구사항에 맞게 작성하고 있습니다."],
      validation: [85, "생성 코드와 테스트를 검증하고 있습니다."],
      "kind deployment": [92, "kind 클러스터에서 동작을 확인하고 있습니다."],
      completed: [100, "결과를 정리했습니다."],
    };

    function renderJob(job) {
      state.textContent = job.state;
      state.className = `status status-${job.state}`;
      phase.textContent = job.phase || "running";
      const info = phaseInfo[job.phase] || [15, "Agent가 작업을 진행하고 있습니다."];
      progress.style.width = `${info[0]}%`;
      title.textContent = info[1];
      stdout.textContent = job.stdoutTail || "";
      stderr.textContent = job.stderrTail || "";
      stdout.scrollTop = stdout.scrollHeight;
      if (job.terminal) window.location.reload();
    }

    cancel?.addEventListener("click", async () => {
      cancel.disabled = true;
      await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      window.location.reload();
    });

    const events = new EventSource(`/api/jobs/${jobId}/events`);
    events.onmessage = (event) => renderJob(JSON.parse(event.data));
    events.onerror = () => {
      events.close();
      window.setTimeout(() => window.location.reload(), 1500);
    };
  }

  const retry = document.getElementById("retry-job");
  retry?.addEventListener("click", async () => {
    retry.disabled = true;
    const jobId = window.location.pathname.split("/").pop();
    const response = await fetch(`/api/jobs/${jobId}/retry`, {
      method: "POST",
    });
    const result = await response.json();
    if (response.ok) {
      window.location.href = `/runs/job/${result.jobId}`;
    } else {
      retry.disabled = false;
      window.alert(result.error || "다시 시도할 수 없습니다.");
    }
  });
})();
