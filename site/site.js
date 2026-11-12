// Language switch, pictures for the chosen language, the feature list, and the latest release for the download buttons.
(function () {
  var REPO = "covriknapoly-glitch/piven-companion";
  var root = document.documentElement;
  var release = null;
  var TEXT = {
    ru: { description: "ИИ-агент для Windows, который работает прямо на твоём компьютере.", platform: "Windows 10 и 11", free: "бесплатно", gb: "ГБ", mb: "МБ" },
    en: { description: "An AI agent for Windows that runs on your own PC.", platform: "Windows 10 and 11", free: "free", gb: "GB", mb: "MB" },
  };

  function size(bytes, lang) {
    var gb = bytes / Math.pow(1024, 3);
    var text = gb >= 1 ? gb.toFixed(1) + " " + TEXT[lang].gb : Math.round(bytes / Math.pow(1024, 2)) + " " + TEXT[lang].mb;
    return lang === "ru" ? text.replace(".", ",") : text;
  }

  function showRelease(lang) {
    var line = document.querySelector("[data-release]");
    if (!line || !release) return;
    var parts = [release.version];
    if (release.bytes) parts.push(size(release.bytes, lang));
    parts.push(TEXT[lang].platform, TEXT[lang].free);
    line.textContent = parts.join(" · ");
  }

  function setLanguage(lang) {
    root.lang = lang;
    root.dataset.lang = lang;
    try { localStorage.setItem("piven-site-lang", lang); } catch (error) {}
    document.querySelector('meta[name="description"]').setAttribute("content", TEXT[lang].description);
    document.querySelectorAll("[data-set-lang]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.setLang === lang));
    });
    document.querySelectorAll("img[data-shot]").forEach(function (image) {
      image.src = "shots/" + lang + "-" + image.dataset.shot + ".webp";
    });
    showRelease(lang);
  }

  document.querySelectorAll("[data-set-lang]").forEach(function (button) {
    button.addEventListener("click", function () { setLanguage(button.dataset.setLang); });
  });

  var features = Array.prototype.slice.call(document.querySelectorAll(".feature"));
  function choose(chosen) {
    features.forEach(function (feature) {
      var on = feature === chosen;
      feature.querySelector(".feature-text").setAttribute("aria-pressed", String(on));
      feature.querySelector(".shot").classList.toggle("on", on);
    });
  }
  features.forEach(function (feature) {
    feature.querySelector(".feature-text").addEventListener("click", function () { choose(feature); });
  });
  if (features.length) choose(features[0]);

  setLanguage(root.dataset.lang === "ru" ? "ru" : "en");

  fetch("https://api.github.com/repos/" + REPO + "/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
    .then(function (response) { return response.ok ? response.json() : null; })
    .then(function (data) {
      if (!data || !data.tag_name) return;
      var setup = (data.assets || []).filter(function (asset) { return /setup\.exe$/i.test(asset.name); })[0];
      release = { version: data.tag_name, bytes: setup ? setup.size : 0 };
      if (setup) {
        document.querySelectorAll("[data-download]").forEach(function (link) { link.href = setup.browser_download_url; });
      }
      showRelease(root.dataset.lang);
    })
    .catch(function () {});
})();
