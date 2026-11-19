const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("axiom", {
  getApiBase: () => ipcRenderer.invoke("axiom:api-base"),
  sidecarStatus: () => ipcRenderer.invoke("axiom:sidecar-status"),
  restartSidecar: () => ipcRenderer.invoke("axiom:restart-sidecar"),
  onSidecar: (callback) => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on("axiom:sidecar", listener)
    return () => ipcRenderer.removeListener("axiom:sidecar", listener)
  },
  openLogs: () => ipcRenderer.invoke("axiom:open-logs"),
  window: {
    minimize: () => ipcRenderer.send("window:minimize"),
    maximize: () => ipcRenderer.send("window:maximize"),
    close: () => ipcRenderer.send("window:close"),
  },
  notify: (title, body) => ipcRenderer.invoke("notify", { title, body }),
})
