(function () {
  "use strict";

  var form = document.getElementById("submit-form");
  if (!form) return;

  var textarea = document.getElementById("sequences");
  var fileInput = document.getElementById("file");
  var dropzone = document.getElementById("dropzone");
  var errors = document.getElementById("form-errors");
  var button = document.getElementById("submit-button");
  var count = document.getElementById("sequence-count");
  var tabs = { paste: document.getElementById("tab-paste"), upload: document.getElementById("tab-upload") };
  var panes = { paste: document.getElementById("pane-paste"), upload: document.getElementById("pane-upload") };
  var mode = "paste";
  var minAligners = Number(form.dataset.minAligners);
  var maxBytes = Number(form.dataset.maxUploadBytes);

  function selectTab(name) {
    mode = name;
    Object.keys(tabs).forEach(function (key) {
      tabs[key].setAttribute("aria-selected", String(key === name));
      panes[key].hidden = key !== name;
    });
  }
  tabs.paste.addEventListener("click", function () { selectTab("paste"); });
  tabs.upload.addEventListener("click", function () { selectTab("upload"); });

  function updateCount() {
    var n = (textarea.value.match(/^\s*>/gm) || []).length;
    count.textContent = n ? n + (n === 1 ? " sequence" : " sequences") : "";
  }
  textarea.addEventListener("input", updateCount);

  document.getElementById("load-example").addEventListener("click", function () {
    textarea.value = document.getElementById("example-fasta").content.textContent.trim() + "\n";
    updateCount();
    textarea.focus();
  });

  ["dragenter", "dragover"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      dropzone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    dropzone.addEventListener(type, function () { dropzone.classList.remove("is-over"); });
  });
  dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    if (event.dataTransfer.files.length) fileInput.files = event.dataTransfer.files;
    showFileName();
  });
  fileInput.addEventListener("change", showFileName);
  function showFileName() {
    var strong = dropzone.querySelector("strong");
    strong.textContent = fileInput.files.length ? fileInput.files[0].name : "Choose a FASTA file";
  }

  var copy = document.getElementById("copy-bibtex");
  if (copy && navigator.clipboard) {
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(document.getElementById("bibtex").textContent).then(function () {
        document.getElementById("copy-status").textContent = "Copied.";
      });
    });
  } else if (copy) {
    copy.hidden = true;
  }

  function showErrors(messages) {
    errors.textContent = "";
    var title = document.createElement("strong");
    title.textContent = messages.length === 1 ? "Fix this before submitting:" : "Fix these before submitting:";
    var list = document.createElement("ul");
    messages.forEach(function (message) {
      var item = document.createElement("li");
      item.textContent = message;
      list.appendChild(item);
    });
    errors.append(title, list);
    errors.hidden = false;
    errors.focus();
  }

  function clientErrors() {
    var problems = [];
    if (mode === "paste" && !textarea.value.trim()) problems.push("Paste your sequences, or switch to Upload a file.");
    if (mode === "upload" && !fileInput.files.length) problems.push("Choose a FASTA file to upload.");
    if (mode === "upload" && fileInput.files.length && fileInput.files[0].size > maxBytes) {
      problems.push("The file is larger than " + maxBytes / 1048576 + " MB.");
    }
    var checked = form.querySelectorAll('input[name="aligners"]:checked').length;
    if (checked < minAligners) problems.push("Select at least " + minAligners + " aligners.");
    return problems;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var problems = clientErrors();
    if (problems.length) return showErrors(problems);

    var data = new FormData(form);
    if (mode === "paste") data.delete("file"); else data.delete("sequences");

    errors.hidden = true;
    button.disabled = true;
    button.textContent = "Submitting…";

    fetch(form.action, { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (result) {
        if (result.status !== 201) {
          showErrors(result.body.errors || ["The server could not accept the job (HTTP " + result.status + "). Try again in a moment."]);
          return;
        }
        var sequences = mode === "paste" ? (textarea.value.match(/^\s*>/gm) || []).length : "";
        window.wpsbootRecent.add({ id: result.body.id, createdAt: new Date().toISOString(), sequences: sequences });
        window.location.assign(result.body.result_url);
      })
      .catch(function () {
        showErrors(["The server could not be reached. Check your connection and try again."]);
      })
      .finally(function () {
        button.disabled = false;
        button.textContent = "Build Super-MSA";
      });
  });

  updateCount();
})();
