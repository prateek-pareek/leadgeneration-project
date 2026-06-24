const statusEl = document.getElementById("status");
const pendingEl = document.getElementById("pending");
const clearBtn = document.getElementById("clear");

chrome.runtime.sendMessage({ action: "getPendingComment" }, (response) => {
  const pending = response?.pending;
  if (pending?.text) {
    statusEl.textContent = `Ready on ${pending.platform || "platform"} — open the post tab.`;
    pendingEl.style.display = "block";
    pendingEl.textContent = pending.text;
  } else {
    statusEl.textContent = "No pending comment. Use Assist post in ProspectOS.";
    pendingEl.style.display = "none";
  }
});

clearBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ action: "clearPendingComment" }, () => {
    statusEl.textContent = "Pending comment cleared.";
    pendingEl.style.display = "none";
  });
});
