// Recent jobs are remembered only in this browser (localStorage).
(function () {
  "use strict";

  var KEY = "wpsboot.recentJobs";
  var MAX = 20;

  function load() {
    try {
      var jobs = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(jobs) ? jobs : [];
    } catch (e) {
      return [];
    }
  }

  function save(jobs) {
    try {
      localStorage.setItem(KEY, JSON.stringify(jobs.slice(0, MAX)));
    } catch (e) {
      /* storage unavailable: history is a convenience only */
    }
  }

  window.wpsbootRecent = {
    add: function (job) {
      save([job].concat(load().filter(function (j) { return j.id !== job.id; })));
    },
    remove: function (id) {
      save(load().filter(function (j) { return j.id !== id; }));
    },
  };

  var table = document.getElementById("recent-table");
  if (!table) return;
  var empty = document.getElementById("recent-empty");
  var body = table.querySelector("tbody");
  var jobs = load();
  if (!jobs.length) return;

  empty.hidden = true;
  table.hidden = false;

  jobs.forEach(function (job) {
    var row = document.createElement("tr");
    var when = new Date(job.createdAt);
    var status = document.createElement("span");
    status.className = "status status-queued";
    status.textContent = "checking";
    var link = document.createElement("a");
    link.href = "/jobs/" + job.id;
    link.className = "mono";
    link.textContent = job.id.slice(0, 8);

    [when.toLocaleString(), String(job.sequences || "")].forEach(function (text, i) {
      var cell = document.createElement("td");
      cell.textContent = text;
      if (i === 1) cell.className = "num";
      row.appendChild(cell);
    });
    [status, link].forEach(function (node) {
      var cell = document.createElement("td");
      cell.appendChild(node);
      row.appendChild(cell);
    });
    body.appendChild(row);

    fetch("/api/v1/jobs/" + job.id, { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (res.status === 404) {
          window.wpsbootRecent.remove(job.id);
          row.remove();
          if (!body.children.length) { table.hidden = true; empty.hidden = false; }
          return null;
        }
        return res.ok ? res.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        status.className = "status status-" + data.status;
        status.textContent = data.status;
      })
      .catch(function () { status.textContent = "unknown"; });
  });
})();
