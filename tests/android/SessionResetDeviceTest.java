package com.example.webkiosk.session7tests;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

/** Synthetic data only; never targets the installed production kiosk. */
public final class SessionResetDeviceTest extends Instrumentation {
    private static final String PACKAGE = "com.example.webkiosk.session7fixture";
    private static final String HOME = "https://www.ucdenver.edu/offices/equity";
    private Activity activity;
    private Bundle arguments;
    private int checks;

    @Override public void onCreate(Bundle args) { arguments = args; start(); }

    private Object field(Object target, String name) {
        try {
            Field f = target.getClass().getDeclaredField(name);
            f.setAccessible(true);
            return f.get(target);
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private void call(String name) {
        try {
            Method m = activity.getClass().getDeclaredMethod(name);
            m.setAccessible(true);
            m.invoke(activity);
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private WebView web() { return (WebView) field(activity, "webView"); }
    private boolean resetting() { return (Boolean) field(activity, "resetting"); }
    private boolean covered() { return ((View) field(activity, "sessionCover")).getVisibility() == View.VISIBLE; }

    private boolean onMain(BooleanSupplier condition) {
        AtomicReference<Boolean> result = new AtomicReference<>();
        runOnMainSync(() -> result.set(condition.getAsBoolean()));
        return result.get();
    }

    private void await(BooleanSupplier condition, String label) {
        long until = SystemClock.elapsedRealtime() + 15000;
        while (SystemClock.elapsedRealtime() < until) {
            if (onMain(condition)) return;
            SystemClock.sleep(25);
        }
        throw new AssertionError("Timed out: " + label);
    }

    private void check(boolean result, String label) {
        if (!result) throw new AssertionError(label);
        checks++;
        Bundle status = new Bundle();
        status.putString("stream", "PASS " + label + "\n");
        sendStatus(0, status);
    }

    private String js(String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        runOnMainSync(() -> web().evaluateJavascript(script, value -> { result.set(value); done.countDown(); }));
        if (!done.await(5, TimeUnit.SECONDS)) throw new AssertionError("JavaScript timeout");
        return result.get();
    }

    private void syntheticHome() {
        runOnMainSync(() -> {
            web().stopLoading();
            web().loadDataWithBaseURL(HOME,
                    "<!doctype html><title>S7 synthetic</title><input id='marker'><p>New session</p>",
                    "text/html", "UTF-8", HOME);
        });
        await(() -> !resetting() && !covered() && web().getProgress() == 100, "synthetic homepage ready");
    }

    private void settleReset() {
        await(() -> !resetting() || (Boolean) field(activity, "resetLoading"), "cookie/storage cleanup");
        syntheticHome();
    }

    private void launch() {
        Intent launch = new Intent().setClassName(PACKAGE, "com.example.webkiosk.MainActivity");
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        activity = startActivitySync(launch);
        if (activity == null) throw new AssertionError("Fixture did not launch");
        settleReset();
    }

    private void seed() throws Exception {
        syntheticHome();
        runOnMainSync(() -> web().getSettings().setDomStorageEnabled(true));
        check("\"seeded\"".equals(js("document.getElementById('marker').value='S7-SYNTHETIC';"
                + "localStorage.setItem('s7','S7-SYNTHETIC');sessionStorage.setItem('s7','S7-SYNTHETIC');"
                + "history.pushState({},'', '/s7-one');history.pushState({},'', '/s7-two');'seeded'")),
                "synthetic form, DOM storage and multiple history entries seeded");
        runOnMainSync(() -> {
            CookieManager cookies = CookieManager.getInstance();
            cookies.setCookie(HOME, "s7=S7-SYNTHETIC; Secure; Path=/");
            cookies.setCookie(HOME, "s7_http=S7-SYNTHETIC; Secure; HttpOnly; Path=/");
            cookies.flush();
            check(cookies.getCookie(HOME).contains("s7_http"), "persistent HttpOnly cookie seeded");
            check(web().canGoBack(), "prior browsing history exists");
        });
    }

    private void assertClean() throws Exception {
        check(onMain(() -> !web().canGoBack()), "new homepage is the only Back entry");
        check(onMain(() -> CookieManager.getInstance().getCookie(HOME) == null), "cookie store has no prior cookies");
        check("false".equals(js("document.cookie.includes('S7-SYNTHETIC')")), "fresh fixture observes no old cookie");
        check("\"\"".equals(js("document.getElementById('marker').value")), "old form value is absent");
        check(onMain(() -> !web().getSettings().getDomStorageEnabled()), "production DOM storage policy restored");
        runOnMainSync(() -> web().getSettings().setDomStorageEnabled(true));
        check("true".equals(js("localStorage.getItem('s7')===null && sessionStorage.getItem('s7')===null")),
                "local and session storage markers are absent");
        runOnMainSync(() -> {
            web().getSettings().setDomStorageEnabled(false);
            for (int i = 0; i < 4; i++) web().goBack();
        });
        check("\"\"".equals(js("document.getElementById('marker').value")), "repeated Back cannot restore the old form");
    }

    private WebResourceRequest request(String url) {
        return new WebResourceRequest() {
            public Uri getUrl() { return Uri.parse(url); }
            public boolean isForMainFrame() { return true; }
            public boolean isRedirect() { return false; }
            public boolean hasGesture() { return false; }
            public String getMethod() { return "GET"; }
            public Map<String, String> getRequestHeaders() { return Collections.emptyMap(); }
        };
    }

    private Runnable holdCleanup() {
        AtomicReference<Runnable> completion = new AtomicReference<>();
        runOnMainSync(() -> {
            try {
                Object cleanup = field(activity, "SESSION_CLEANUP");
                Class<?> cleaner = Class.forName("com.example.webkiosk.SessionCleanup$Cleaner", true,
                        activity.getClassLoader());
                Object proxy = Proxy.newProxyInstance(activity.getClassLoader(), new Class<?>[]{cleaner},
                        (object, method, args) -> { completion.set((Runnable) args[0]); return null; });
                cleanup.getClass().getMethod("request", cleaner, Runnable.class)
                        .invoke(cleanup, proxy, (Runnable) () -> {});
            } catch (Exception e) { throw new IllegalStateException(e); }
        });
        if (completion.get() == null) throw new AssertionError("Could not hold cleanup completion");
        return completion.get();
    }

    private void timeout() {
        try {
            Object deadline = field(activity, "inactivityDeadline");
            Field last = deadline.getClass().getDeclaredField("lastInteraction");
            last.setAccessible(true);
            last.setLong(deadline, SystemClock.elapsedRealtime() - 180001);
            ((Runnable) field(activity, "inactivityRunnable")).run();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private void delayedAndTimeout() throws Exception {
        seed();
        Runnable release = holdCleanup();
        AtomicReference<WebView> old = new AtomicReference<>();
        AtomicReference<WebViewClient> client = new AtomicReference<>();
        runOnMainSync(() -> {
            old.set(web()); client.set(web().getWebViewClient());
            timeout();
            check(resetting() && covered() && web() != old.get(), "timeout retires old WebView before cleanup completes");
            check(web().getUrl() == null && !web().isEnabled(), "replacement has no request while deletion is delayed");
            for (int i = 0; i < 10; i++) call("beginFreshSession");
            client.get().onPageFinished(old.get(), HOME);
            client.get().onPageStarted(old.get(), HOME, (Bitmap) null);
            check(resetting() && covered() && web().getUrl() == null, "rapid reset and stale callbacks cannot open old content");
            check(client.get().shouldInterceptRequest(old.get(), request(HOME)) != null,
                    "retired client rejects late requests");
        });
        SystemClock.sleep(300);
        check(onMain(() -> covered() && web().getUrl() == null), "next-session navigation waits for delayed cleanup");
        runOnMainSync(release);
        settleReset();
        assertClean();
    }

    private void failedHomepage() throws Exception {
        seed();
        runOnMainSync(() -> call("beginFreshSession"));
        await(() -> (Boolean) field(activity, "resetLoading"), "replacement for failed load");
        runOnMainSync(() -> {
            web().stopLoading();
            // The production handler only consumes the main-frame flag; no framework
            // WebResourceError constructor is public in the Android SDK stubs.
            web().getWebViewClient().onReceivedError(web(), request(HOME), null);
            check(!resetting() && !covered() && web().getVisibility() != View.VISIBLE,
                    "offline callback shows native error without old content");
            check(((View) field(activity, "errorLayout")).isShown(), "native error view is visible");
            check(!web().canGoBack(), "failed homepage has no old history");
            check(CookieManager.getInstance().getCookie(HOME) == null, "offline reset still removes cookies");
            ((View) field(activity, "btnRetry")).performClick();
        });
        syntheticHome();
        assertClean();
    }

    private void recreateDuringCleanup() throws Exception {
        seed();
        Runnable release = holdCleanup();
        Activity old = activity;
        ActivityMonitor monitor = addMonitor("com.example.webkiosk.MainActivity", null, false);
        runOnMainSync(() -> { call("beginFreshSession"); old.recreate(); });
        activity = waitForMonitorWithTimeout(monitor, 15000);
        removeMonitor(monitor);
        check(activity != null && activity != old, "rotation/recreation replaces the activity");
        check(onMain(() -> covered() && web().getUrl() == null), "recreated activity stays covered behind pending cleanup");
        runOnMainSync(release);
        settleReset();
        assertClean();
    }

    private void exit() throws Exception {
        seed();
        Runnable release = holdCleanup();
        IntentFilter home = new IntentFilter(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        ActivityMonitor homeMonitor = addMonitor(home, new ActivityResult(Activity.RESULT_OK, null), true);
        try {
            runOnMainSync(() -> {
                call("exitToHome");
                check(covered() && !activity.isFinishing(), "explicit exit waits for cleanup");
                call("exitToHome");
            });
            runOnMainSync(release);
            await(() -> activity.isFinishing(), "explicit exit finishes old activity");
            check(onMain(() -> CookieManager.getInstance().getCookie(HOME) == null), "exit removes persisted cookies before Home");
            check(homeMonitor.getHits() == 1, "repeated exit produces one Home transition");
        } finally { removeMonitor(homeMonitor); }
        launch();
        assertClean();
    }

    private void navigation() {
        runOnMainSync(() -> {
            WebViewClient client = web().getWebViewClient();
            check(!client.shouldOverrideUrlLoading(web(), request(HOME)), "approved HTTPS navigation still allowed");
            check(client.shouldOverrideUrlLoading(web(), request("https://attackerucdenver.edu/")),
                    "look-alike hostname still blocked");
            check(client.shouldOverrideUrlLoading(web(), request("http://www.ucdenver.edu/")),
                    "HTTP navigation still blocked");
        });
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!PACKAGE.equals(getTargetContext().getPackageName())) throw new AssertionError("Wrong target package");
            launch();
            if ("restart".equals(arguments.getString("phase"))) {
                check(onMain(() -> CookieManager.getInstance().getCookie(HOME) == null), "restart clears persisted synthetic cookie");
                assertClean();
            } else {
                delayedAndTimeout();
                failedHomepage();
                recreateDuringCleanup();
                exit();
                navigation();
                seed(); // Runner force-stops only the fixture before the restart phase.
            }
            result.putString("session7_status", "PASS");
            result.putInt("session7_checks", checks);
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            result.putString("session7_status", "FAIL");
            result.putString("session7_failure", failure.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
