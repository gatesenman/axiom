export async function notifyFinished(title: string, body: string) {
  if (localStorage.getItem("axiom.notify") === "0") return
  try {
    if (window.axiom?.notify) {
      await window.axiom.notify(title, body)
    } else if (typeof Notification !== "undefined") {
      let permission = Notification.permission
      if (permission === "default") permission = await Notification.requestPermission()
      if (permission === "granted") new Notification(title, { body })
    }
  } catch {
    /* the solve itself already finished; a blocked notification is not an error */
  }
  if (localStorage.getItem("axiom.sound") === "1") beep()
}

function beep() {
  const context = new AudioContext()
  const osc = context.createOscillator()
  const gain = context.createGain()
  osc.frequency.value = 880
  gain.gain.value = 0.04
  osc.connect(gain)
  gain.connect(context.destination)
  osc.start()
  osc.stop(context.currentTime + 0.12)
  osc.onended = () => void context.close()
}
