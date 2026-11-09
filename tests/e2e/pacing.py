"""
Browser pacing for the e2e suite.

pause(seconds) replaces a fixed sleep after a browser action: it returns as
soon as the page is idle and waits at most `seconds`. Idle means the document
is loaded and has no navigation, request, due timer or finite animation
pending, and nothing happened on it for QUIET_MS.

The page reports its own state through IDLE_TRACKER_JS, which the driver
fixture installs into every new document.
"""
import os
import time

from selenium.common.exceptions import WebDriverException

QUIET_MS = 80
POLL_SECONDS = 0.01

# Appends "<waited> <cap> <last busy reason>" per pause, to tune the tracker.
PAUSE_LOG = os.environ.get("E2E_PAUSE_LOG", "")

IDLE_TRACKER_JS = r"""
(function () {
  if (window.__e2eIdle) return;
  var now = function () { return performance.now(); };
  var state = { pending: 0, last: now(), leaving: false, timers: new Map() };
  var touch = function () { state.last = now(); };

  var track = function (promise) {
    state.pending++; touch();
    var done = function () { state.pending--; touch(); };
    promise.then(done, done);
    return promise;
  };

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function () { return track(origFetch.apply(this, arguments)); };
    ['json', 'text', 'blob', 'arrayBuffer', 'formData'].forEach(function (name) {
      var orig = Response.prototype[name];
      Response.prototype[name] = function () { return track(orig.apply(this, arguments)); };
    });
  }

  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    state.pending++; touch();
    this.addEventListener('loadend', function () { state.pending--; touch(); });
    return origSend.apply(this, arguments);
  };

  ['readAsDataURL', 'readAsText', 'readAsArrayBuffer'].forEach(function (name) {
    var orig = FileReader.prototype[name];
    FileReader.prototype[name] = function () {
      state.pending++; touch();
      this.addEventListener('loadend', function () { state.pending--; touch(); }, { once: true });
      return orig.apply(this, arguments);
    };
  });

  var origToBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function (callback) {
    var args = Array.prototype.slice.call(arguments);
    state.pending++; touch();
    args[0] = function (blob) { state.pending--; touch(); callback(blob); };
    return origToBlob.apply(this, args);
  };

  // covers detached images, which document.images never lists
  var srcProp = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  var loadingImages = new WeakSet();
  Object.defineProperty(HTMLImageElement.prototype, 'src', {
    configurable: true, enumerable: true, get: srcProp.get,
    set: function (value) {
      if (value && !loadingImages.has(this)) {
        var img = this;
        loadingImages.add(img); state.pending++; touch();
        var done = function () {
          if (!loadingImages.has(img)) return;
          loadingImages.delete(img); state.pending--; touch();
          img.removeEventListener('load', done); img.removeEventListener('error', done);
        };
        img.addEventListener('load', done); img.addEventListener('error', done);
      }
      srcProp.set.call(this, value);
    },
  });

  var origSetTimeout = window.setTimeout;
  var origClearTimeout = window.clearTimeout;
  window.setTimeout = function (fn, delay) {
    if (typeof fn !== 'function') return origSetTimeout.apply(window, arguments);
    var args = Array.prototype.slice.call(arguments, 2);
    var id = origSetTimeout(function () {
      state.timers.delete(id); touch();
      fn.apply(this, args);
    }, delay);
    state.timers.set(id, now() + (Number(delay) || 0));
    touch();
    return id;
  };
  window.clearTimeout = function (id) {
    state.timers.delete(id);
    return origClearTimeout(id);
  };

  var origRaf = window.requestAnimationFrame;
  window.requestAnimationFrame = function (fn) {
    return origRaf(function (ts) { touch(); fn(ts); });
  };

  new MutationObserver(touch).observe(document, {
    subtree: true, childList: true, attributes: true, characterData: true,
  });

  ['click', 'input', 'change', 'keydown', 'keyup', 'submit', 'pointerdown',
   'pointerup', 'mousedown', 'mouseup', 'focusin', 'focusout', 'scroll',
   'DOMContentLoaded', 'load'].forEach(function (name) {
    window.addEventListener(name, touch, true);
  });
  window.addEventListener('beforeunload', function () { state.leaving = true; touch(); }, true);
  window.addEventListener('pagehide', function () { state.leaving = true; }, true);

  // Returns '' when idle, else the reason; 'active:<ms>' carries the quiet time left.
  // Timers due after remainingMs are ignored.
  window.__e2eIdle = function (remainingMs, quietMs) {
    var t = now();
    if (document.readyState !== 'complete') return 'loading';
    if (state.leaving) return 'leaving';
    if (state.pending > 0) return 'request';
    var horizon = t + remainingMs;
    var due = false;
    state.timers.forEach(function (at) { if (at <= horizon) due = true; });
    if (due) return 'timer';
    var imageLoading = Array.prototype.some.call(document.images, function (img) {
      return !img.complete && img.loading !== 'lazy';
    });
    if (imageLoading) return 'image';
    var animating = document.getAnimations().some(function (a) {
      if (a.playState !== 'running' || !a.effect) return false;
      return isFinite(a.effect.getComputedTiming().endTime);
    });
    if (animating) return 'animation';
    if (t - state.last < quietMs) return 'active:' + Math.ceil(quietMs - (t - state.last));
    return '';
  };
})();
"""

_IDLE_CALL = (
    "return window.__e2eIdle ? window.__e2eIdle(arguments[0], arguments[1]) : 'untracked';"
)

_driver = None


def install(driver) -> None:
    """
    Install the idle tracker into every document the driver loads and make it
    the driver pause() asks.

    @param driver  Chrome WebDriver of this test session.
    """
    global _driver
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument", {"source": IDLE_TRACKER_JS}
    )
    _driver = driver


def pause(seconds: float) -> None:
    """
    Wait until the page is idle, at most `seconds`.

    Use after a browser action, before asserting on its effect. For waits the
    page cannot see (server side clocks, cooldowns, timestamps that must
    differ) use time.sleep().

    @param seconds  Upper bound of the wait, the time a fixed sleep would take.
    """
    start = time.monotonic()
    deadline = start + seconds
    reason = "no driver"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if _driver is not None:
            try:
                reason = _driver.execute_script(_IDLE_CALL, remaining * 1000, QUIET_MS)
            except WebDriverException as exc:
                reason = type(exc).__name__
            if reason == "":
                break
        wait = POLL_SECONDS
        if reason.startswith("active:"):
            wait = int(reason[7:]) / 1000
            reason = "active"
        time.sleep(max(0.0, min(wait, deadline - time.monotonic())))
    if PAUSE_LOG:
        with open(PAUSE_LOG, "a") as log:
            log.write(f"{time.monotonic() - start:.3f} {seconds} {reason or 'idle'}\n")
