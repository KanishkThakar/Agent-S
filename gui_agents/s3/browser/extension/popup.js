const dot = document.getElementById("dot");
const statusText = document.getElementById("status");
const portInput = document.getElementById("port");

chrome.runtime.sendMessage({ type: "status" }, (response) => {
  if (!response) return;
  const connected = response.status === "connected";
  dot.classList.toggle("connected", connected);
  statusText.textContent = response.working
    ? "Connected, working in the Agent S tab group"
    : connected
      ? "Connected to agent_s"
      : "Waiting for agent_s to start";
  portInput.value = response.port;
});

portInput.addEventListener("change", () => {
  const port = Number(portInput.value);
  if (port >= 1024 && port <= 65535) chrome.storage.local.set({ port });
});
