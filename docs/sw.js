self.addEventListener("push", function (event) {
  let data = { title: "DC 자비스", body: "" };
  try {
    data = event.data.json();
  } catch (e) {
    data.body = event.data ? event.data.text() : "";
  }

  const options = {
    body: data.body || "",
    icon: data.icon || "https://raw.githubusercontent.com/kkandelo-arch/jarvis/main/docs/icon.png",
    data: { url: data.url || "https://github.com/kkandelo-arch/jarvis" }
  };

  event.waitUntil(self.registration.showNotification(data.title || "DC 자비스", options));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "https://github.com/kkandelo-arch/jarvis";
  event.waitUntil(clients.openWindow(url));
});
