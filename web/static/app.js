(() => {
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {
        // Browser permission can reject Clipboard API; use the local fallback.
      }
    }
    const input = document.createElement("textarea");
    input.value = text;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    return copied;
  }

  const requirementInput = document.getElementById("requirement_text");
  document.querySelectorAll("[data-requirement-example]").forEach((button) => {
    button.addEventListener("click", () => {
      if (
        requirementInput.value.trim()
        && requirementInput.value !== button.dataset.requirementExample
        && !window.confirm("작성 중인 내용이 예제로 바뀝니다. 계속할까요?")
      ) return;
      requirementInput.value = button.dataset.requirementExample;
      requirementInput.focus();
      requirementInput.setSelectionRange(
        requirementInput.value.length,
        requirementInput.value.length,
      );
    });
  });

  document.querySelectorAll(".copy-command").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      const copied = await copyText(target.textContent.trim());
      const original = button.textContent;
      button.textContent = copied ? "복사됨" : "복사 실패";
      window.setTimeout(() => { button.textContent = original; }, 1200);
    });
  });

  const requirementForm = document.getElementById("requirement-form");
  requirementForm?.addEventListener("submit", () => {
    const submit = document.getElementById("primary-submit");
    submit.disabled = true;
    submit.textContent = "계획을 시작하는 중…";
  });

  const logAnalysisForm = document.getElementById("log-analysis-form");
  logAnalysisForm?.addEventListener("submit", () => {
    const submit = document.getElementById("log-analysis-submit");
    if (!submit) return;
    submit.disabled = true;
    submit.textContent = "로그 분석을 시작하는 중…";
  });

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
    const elapsed = document.getElementById("job-elapsed");
    let startedAt = parseTimestamp(panel.dataset.startedAt);

    const stateLabels = {
      queued: "대기 중",
      running: "진행 중",
      succeeded: "완료",
      failed: "실패",
      canceled: "취소됨",
      interrupted: "중단됨",
    };

    const phaseInfo = {
      queued: [5, "작업을 시작할 준비를 하고 있습니다.", "작업 준비"],
      starting: [10, "Agent를 시작하고 있습니다.", "Agent 시작"],
      "LLM planning": [20, "요구사항을 이해하고 계획을 만들고 있습니다.", "요구사항 분석과 계획 생성"],
      "LLM planning completed": [30, "계획을 확인했습니다.", "계획 생성 완료"],
      "spec generation": [42, "Operator 구조를 정리하고 있습니다.", "Operator 구조 설계"],
      "command planning": [50, "안전한 실행 순서를 만들고 있습니다.", "안전한 실행 순서 구성"],
      scaffold: [62, "Operator 프로젝트를 생성하고 있습니다.", "프로젝트 생성"],
      "artifact patch": [72, "Controller 코드를 요구사항에 맞게 작성하고 있습니다.", "Controller 코드 생성"],
      validation: [85, "생성 코드와 테스트를 검증하고 있습니다.", "코드와 테스트 검증"],
      "kind deployment": [92, "로컬 클러스터에서 동작을 확인하고 있습니다.", "로컬 클러스터 검증"],
      "log analysis": [65, "실패 로그에서 원인과 해결 방법을 찾고 있습니다.", "로그 원인 분석"],
      completed: [100, "결과를 정리했습니다.", "결과 정리 완료"],
    };

    function parseTimestamp(value) {
      const parsed = Date.parse(value || "");
      return Number.isNaN(parsed) ? Date.now() : parsed;
    }

    function formatElapsed(milliseconds) {
      const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      if (hours) return `${hours}시간 ${minutes}분 ${seconds}초 경과`;
      if (minutes) return `${minutes}분 ${seconds}초 경과`;
      return `${seconds}초 경과`;
    }

    function updateElapsed() {
      if (elapsed) elapsed.textContent = formatElapsed(Date.now() - startedAt);
    }

    function renderJob(job) {
      if (job.startedAt) startedAt = parseTimestamp(job.startedAt);
      state.textContent = stateLabels[job.state] || job.state;
      state.className = `status status-${job.state}`;
      const info = phaseInfo[job.phase] || [15, "Agent가 작업을 진행하고 있습니다.", "작업 진행"];
      phase.textContent = info[2];
      progress.style.width = `${info[0]}%`;
      title.textContent = info[1];
      stdout.textContent = job.stdoutTail || "";
      stderr.textContent = job.stderrTail || "";
      stdout.scrollTop = stdout.scrollHeight;
      if (job.terminal) window.location.reload();
    }

    updateElapsed();
    window.setInterval(updateElapsed, 1000);

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
