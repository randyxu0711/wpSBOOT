(function () {
  "use strict";

  var POLL_MS = 3000;
  var ACTIVE = ["queued", "running"];
  var STEP_TEXT = {
    pending: "waiting",
    running: "running",
    succeeded: "done",
    failed: "failed",
    timed_out: "time limit exceeded",
    cancelled: "stopped",
    skipped: "skipped",
  };
  var LABELS = { mafft: "MAFFT", muscle: "MUSCLE", clustalw: "ClustalW", tcoffee: "T-Coffee" };

  var job = JSON.parse(document.getElementById("job-data").textContent);
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) { node.appendChild(child); });
    return node;
  }

  function duration(seconds) {
    if (seconds == null) return "";
    if (seconds < 60) return seconds.toFixed(1) + " s";
    var m = Math.floor(seconds / 60);
    return m + " min " + Math.round(seconds - m * 60) + " s";
  }

  function size(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function stepNode(step) {
    return el("div", { class: "step seg-" + step.name }, [
      el("span", { class: "name", text: step.label }),
      el("span", { class: "meta" }, [
        el("span", { text: duration(step.duration_seconds) }),
        el("span", { class: "status status-" + step.status, text: STEP_TEXT[step.status] || step.status }),
      ]),
    ]);
  }

  function message() {
    var box = $("job-message");
    box.textContent = "";
    var alerts = [];
    if (job.status === "queued") {
      alerts.push(["info", job.queue_position > 1
        ? "Waiting in the queue: " + (job.queue_position - 1) + " job(s) ahead of yours. This page updates on its own."
        : "Starting soon. This page updates on its own."]);
    } else if (job.status === "running") {
      alerts.push(["info", "Aligning your sequences. This page updates on its own; you can also bookmark it and come back later."]);
    } else if (job.status === "failed") {
      alerts.push(["error", job.error || "The job failed."]);
    } else if (job.status === "expired") {
      alerts.push(["info", "This job’s files were deleted after the retention period. Submit the sequences again to rebuild the Super-MSA."]);
    }
    if (job.warnings.length) alerts.push(["warn", job.warnings]);
    alerts.forEach(function (alert) {
      var node = el("div", { class: "alert alert-" + alert[0] });
      if (Array.isArray(alert[1])) {
        node.appendChild(el("strong", { text: "Notes about this job" }));
        node.appendChild(el("ul", {}, alert[1].map(function (w) { return el("li", { text: w }); })));
      } else {
        node.textContent = alert[1];
      }
      box.appendChild(node);
    });
  }

  function render() {
    var status = $("job-status");
    status.className = "status status-" + job.status;
    status.textContent = job.status;
    $("expires-row").hidden = ["expired", "deleted"].indexOf(job.status) !== -1;
    message();

    var aligners = $("aligner-steps");
    aligners.textContent = "";
    job.steps.filter(function (s) { return s.name !== "concatenate"; }).forEach(function (s) {
      aligners.appendChild(stepNode(s));
    });
    var concat = $("concat-step");
    concat.textContent = "";
    job.steps.filter(function (s) { return s.name === "concatenate"; }).forEach(function (s) {
      concat.appendChild(stepNode(s));
    });

    var order = job.concatenation_order || [];
    $("order-section").hidden = !order.length;
    $("order-bar").textContent = "";
    order.forEach(function (name) {
      $("order-bar").appendChild(el("span", { class: "seg-" + name, text: LABELS[name] || name }));
    });

    $("files-section").hidden = !job.files.length;
    $("files-body").textContent = "";
    job.files.forEach(function (file) {
      $("files-body").appendChild(el("tr", {}, [
        el("td", {}, [el("a", { href: file.url, class: "mono", download: file.name, text: file.name })]),
        el("td", { text: file.label }),
        el("td", { class: "num", text: size(file.size_bytes) }),
      ]));
    });
    if (job.archive_url) $("archive-link").href = job.archive_url;

    var details = $("aligner-details");
    details.textContent = "";
    details.append(el("dt", { text: "Selected" }), el("dd", { text: job.aligners.map(function (a) { return LABELS[a] || a; }).join(", ") }));
    if (job.started_at) details.append(el("dt", { text: "Started" }), el("dd", { text: new Date(job.started_at).toLocaleString() }));
    if (job.finished_at) details.append(el("dt", { text: "Finished" }), el("dd", { text: new Date(job.finished_at).toLocaleString() }));

    if (job.tool_versions) {
      var versions = $("version-details");
      versions.textContent = "";
      Object.keys(job.tool_versions).forEach(function (name) {
        versions.append(el("dt", { text: name }), el("dd", { class: "mono", text: String(job.tool_versions[name]) }));
      });
    }
    $("delete-job").hidden = job.status === "expired";
  }

  function poll() {
    if (ACTIVE.indexOf(job.status) === -1) return;
    setTimeout(function () {
      fetch("/api/v1/jobs/" + job.id, { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (res) {
          if (res.status === 404) { window.location.reload(); return null; }
          return res.ok ? res.json() : null;
        })
        .then(function (data) { if (data) { job = data; render(); } })
        .catch(function () { /* transient network error: try again */ })
        .finally(poll);
    }, POLL_MS);
  }

  $("delete-job").addEventListener("click", function () {
    if (!window.confirm("Delete this job and all of its files? This cannot be undone.")) return;
    var button = $("delete-job");
    button.disabled = true;
    fetch("/api/v1/jobs/" + job.id, { method: "DELETE" }).then(function (res) {
      if (res.status === 204 || res.status === 404) {
        window.wpsbootRecent.remove(job.id);
        window.location.assign("/#recent");
      } else {
        button.disabled = false;
        window.alert("The job could not be deleted (HTTP " + res.status + "). Try again.");
      }
    });
  });

  document.querySelectorAll("time[data-local]").forEach(function (node) {
    node.textContent = new Date(node.getAttribute("datetime")).toLocaleString();
  });

  render();
  poll();
})();
