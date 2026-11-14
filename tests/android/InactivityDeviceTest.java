package com.example.webkiosk.session6tests;

import android.app.Activity;
import android.app.Application;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebView;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;

/** Runs only against a separate test-only package, with synthetic form data. */
public final class InactivityDeviceTest extends Instrumentation {
    private static final String PACKAGE = "com.example.webkiosk.session6fixture";
    private static final String HOME = "https://www.ucdenver.edu/offices/equity";
    private Activity activity;
    private Bundle arguments;
    private int checks;
    private int replacements;
    private volatile boolean exposedOnResume;
    private WebView expiredView;

    @Override public void onCreate(Bundle args) { arguments = args; start(); }

    private Object field(Object target, String name) {
        try {
            Field field = target.getClass().getDeclaredField(name);
            field.setAccessible(true);
            return field.get(target);
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private void call(String name) {
        try {
            Method method = activity.getClass().getDeclaredMethod(name);
            method.setAccessible(true);
            method.invoke(activity);
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

    private void age(long elapsed) {
        try {
            Object deadline = field(activity, "inactivityDeadline");
            Field last = deadline.getClass().getDeclaredField("lastInteraction");
            last.setAccessible(true);
            last.setLong(deadline, SystemClock.elapsedRealtime() - elapsed);
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private long lastInteraction() { return (Long) field(field(activity, "inactivityDeadline"), "lastInteraction"); }

    private void syntheticPage(String body) {
        runOnMainSync(() -> {
            web().stopLoading();
            // Preserve the production client; its real page-finished callback completes reset.
            web().loadDataWithBaseURL(HOME, "<!doctype html><title>Synthetic session six</title>" + body,
                    "text/html", "UTF-8", HOME);
        });
    }

    private void settleReset() {
        await(() -> !resetting() || (Boolean) field(activity, "resetLoading"), "cleanup/replacement");
        syntheticPage("<p>Fresh synthetic homepage</p>");
        await(() -> !resetting() && !covered(), "new page visible");
    }

    private void seedForm() throws Exception {
        syntheticPage("<input id='marker' value='S6-SYNTHETIC'>");
        long until = SystemClock.elapsedRealtime() + 8000;
        while (SystemClock.elapsedRealtime() < until) {
            if ("\"S6-SYNTHETIC\"".equals(js("document.getElementById('marker')?.value"))) return;
            SystemClock.sleep(50);
        }
        throw new AssertionError("Synthetic form did not load");
    }

    private String js(String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        runOnMainSync(() -> web().evaluateJavascript(script, value -> { result.set(value); done.countDown(); }));
        if (!done.await(5, TimeUnit.SECONDS)) throw new AssertionError("JavaScript timeout");
        return result.get();
    }

    private void assertExpiredAndCovered() {
        check(resetting() && covered() && expiredView.getVisibility() != View.VISIBLE
                && !expiredView.isEnabled(), "expired content covered and disabled before resume/input returns");
        activity.onUserInteraction();
        activity.onUserInteraction();
        check(resetting() && covered(), "repeated input cannot reopen an expired session");
    }

    private void completeAndCheckReplacement() {
        settleReset();
        check(onMain(() -> web() != expiredView), "expired WebView replaced");
        check(onMain(() -> replacements == 1), "reset creates exactly one replacement");
    }

    private void watchReplacement() {
        replacements = 0;
        ((ViewGroup) web().getParent()).setOnHierarchyChangeListener(new ViewGroup.OnHierarchyChangeListener() {
            @Override public void onChildViewAdded(View parent, View child) { if (child instanceof WebView) replacements++; }
            @Override public void onChildViewRemoved(View parent, View child) {}
        });
    }

    private void lifecycleSuite() throws Exception {
        seedForm();
        runOnMainSync(() -> {
            age(120000);
            long before = lastInteraction();
            call("onPause");
            check(covered() && !web().isEnabled(), "pause covers content");
            call("onResume");
            check(lastInteraction() == before && !resetting(), "pause/resume preserves last real interaction");
            activity.onUserInteraction();
            check(lastInteraction() > before, "actual interaction extends the deadline");
            age(179000);
            before = lastInteraction();
            call("onPause"); call("onResume");
            check(lastInteraction() == before, "resume near expiry retains only the remaining interval");
            // Do not leave a one-second timer running while subsequent fixtures load.
            activity.onUserInteraction();
        });
        runOnMainSync(() -> {
            expiredView = web(); watchReplacement(); age(180001);
            call("onPause"); call("onResume"); assertExpiredAndCovered();
        });
        completeAndCheckReplacement();
        seedForm();
        runOnMainSync(() -> {
            expiredView = web(); watchReplacement(); age(180001);
            ((Runnable) field(activity, "inactivityRunnable")).run();
            assertExpiredAndCovered();
        });
        completeAndCheckReplacement();
        seedForm();
        runOnMainSync(() -> {
            expiredView = web(); watchReplacement(); age(180001);
            check(activity.dispatchKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_A)),
                    "input at expiry is consumed");
            assertExpiredAndCovered();
        });
        completeAndCheckReplacement();

        seedForm();
        Intent wifi = new Intent().setClassName(PACKAGE, "com.example.webkiosk.WifiSettingsActivity");
        wifi.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        Activity other = startActivitySync(wifi);
        await(() -> !(Boolean) field(activity, "resumed"), "actual background transition");
        runOnMainSync(() -> { expiredView = web(); watchReplacement(); age(180001); other.finish(); });
        await(() -> (Boolean) field(activity, "resumed"), "actual activity return");
        check(!exposedOnResume, "real background return never exposes expired form");
        completeAndCheckReplacement();

        seedForm();
        Activity old = activity;
        ActivityMonitor monitor = addMonitor("com.example.webkiosk.MainActivity", null, false);
        runOnMainSync(() -> old.recreate());
        activity = waitForMonitorWithTimeout(monitor, 15000);
        removeMonitor(monitor);
        check(activity != null && activity != old, "activity recreated");
        settleReset();
        check("null".equals(js("document.getElementById('marker')")), "recreation starts a fresh document");
    }

    private void shell(String command) throws Exception {
        try (java.io.InputStream input = new android.os.ParcelFileDescriptor.AutoCloseInputStream(
                getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
                        .executeShellCommand(command))) {
            byte[] buffer = new byte[1024];
            while (input.read(buffer) != -1) {}
        }
    }

    private void screenOff() throws Exception {
        seedForm();
        runOnMainSync(() -> { expiredView = web(); watchReplacement(); });
        shell("input keyevent KEYCODE_SLEEP");
        await(() -> !(Boolean) field(activity, "resumed"), "screen-off pause");
        long until = SystemClock.elapsedRealtime() + 181000;
        while (SystemClock.elapsedRealtime() < until) SystemClock.sleep(250);
        shell("input keyevent KEYCODE_WAKEUP");
        shell("wm dismiss-keyguard");
        await(() -> (Boolean) field(activity, "resumed"), "screen-on resume; unlock if necessary");
        check(!exposedOnResume, "181 seconds screen-off never exposes expired form on resume");
        completeAndCheckReplacement();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if (!PACKAGE.equals(getTargetContext().getPackageName())) throw new AssertionError("Wrong target package");
            Application app = (Application) getTargetContext().getApplicationContext();
            app.registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
                @Override public void onActivityResumed(Activity a) {
                    if (a == activity && expiredView != null && expiredView == web()
                            && expiredView.isShown() && expiredView.isEnabled() && !covered()) exposedOnResume = true;
                }
                @Override public void onActivityCreated(Activity a, Bundle b) {}
                @Override public void onActivityStarted(Activity a) {}
                @Override public void onActivityPaused(Activity a) {}
                @Override public void onActivityStopped(Activity a) {}
                @Override public void onActivitySaveInstanceState(Activity a, Bundle b) {}
                @Override public void onActivityDestroyed(Activity a) {}
            });
            Intent launch = new Intent().setClassName(PACKAGE, "com.example.webkiosk.MainActivity");
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            activity = startActivitySync(launch);
            settleReset();
            if ("restart".equals(arguments.getString("phase"))) {
                check(onMain(() -> CookieManager.getInstance().getCookie(HOME) == null),
                        "process restart clears persisted synthetic cookie before fresh page");
                check("null".equals(js("document.getElementById('marker')")), "process restart has no prior form");
            } else {
                lifecycleSuite();
                if ("true".equals(arguments.getString("screenOff"))) screenOff();
                runOnMainSync(() -> {
                    CookieManager.getInstance().setCookie(HOME, "session6_marker=synthetic; Secure");
                    CookieManager.getInstance().flush();
                    check(CookieManager.getInstance().getCookie(HOME).contains("session6_marker=synthetic"),
                            "persisted synthetic cookie seeded for process-restart phase");
                });
            }
            result.putString("session6_status", "PASS");
            result.putInt("session6_checks", checks);
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            result.putString("session6_status", "FAIL");
            result.putString("session6_failure", failure.toString());
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
