package com.example.webkiosk.navigationtests;

import android.app.Activity;
import android.app.Instrumentation;
import android.app.KeyguardManager;
import android.app.UiAutomation;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.TextUtils;
import android.view.View;
import android.view.accessibility.AccessibilityEvent;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.example.webkiosk.NavigationPolicyTest;

import java.io.ByteArrayInputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import org.json.JSONArray;
import org.json.JSONObject;

public final class NavigationDeviceTest extends Instrumentation {
    private Activity activity;
    private WebView web;
    private WebViewClient original;
    private Method policy;
    private Method loadApproved;
    private String home;
    private Bundle arguments;
    private final Map<String, String> fixtures = new ConcurrentHashMap<>();
    private final AtomicInteger blocked = new AtomicInteger();
    private final AtomicInteger preRequestBlocks = new AtomicInteger();
    private final AtomicInteger safetyFailures = new AtomicInteger();
    private final AtomicInteger finishes = new AtomicInteger();
    private final AtomicInteger toasts = new AtomicInteger();
    private volatile String finishedUrl = "";
    private volatile String liveError = "";
    private volatile boolean synthetic = true;
    private boolean keepScreenWasOn;
    private int sequence;
    private int passed;

    @Override public void onCreate(Bundle args) {
        arguments = args == null ? new Bundle() : args;
        start();
    }

    private void report(String message) {
        Bundle status = new Bundle();
        status.putString("stream", message + "\n");
        sendStatus(0, status);
    }

    private void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private void pass(String label) {
        passed++;
        report("PASS " + label);
    }

    private boolean allowed(String url) {
        try { return (Boolean) policy.invoke(null, url); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }

    private void await(BooleanSupplier condition, String label) {
        long deadline = SystemClock.elapsedRealtime() + 12000;
        while (SystemClock.elapsedRealtime() < deadline) {
            runOnMainSync(this::observeCurrentWebView);
            if (condition.getAsBoolean()) return;
            SystemClock.sleep(50);
        }
        throw new AssertionError("Timed out: " + label + "; URL=" + url());
    }

    private String url() {
        AtomicReference<String> value = new AtomicReference<>();
        runOnMainSync(() -> value.set(web.getUrl()));
        return value.get();
    }

    private String history() {
        AtomicReference<String> value = new AtomicReference<>();
        runOnMainSync(() -> {
            android.webkit.WebBackForwardList list = web.copyBackForwardList();
            StringBuilder text = new StringBuilder("index=" + list.getCurrentIndex());
            for (int i = 0; i < list.getSize(); i++) text.append(" | ").append(i).append(":").append(list.getItemAtIndex(i).getUrl());
            value.set(text.toString());
        });
        return value.get();
    }

    private boolean visible() {
        AtomicReference<Boolean> value = new AtomicReference<>();
        runOnMainSync(() -> value.set(web.getVisibility() == View.VISIBLE));
        return value.get();
    }

    private String js(String script) throws Exception {
        AtomicReference<String> result = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        runOnMainSync(() -> web.evaluateJavascript(script, value -> {
            result.set(value);
            done.countDown();
        }));
        check(done.await(8, TimeUnit.SECONDS), "JavaScript callback timed out");
        return result.get();
    }

    private void appLoad(String url) {
        runOnMainSync(() -> {
            try { loadApproved.invoke(activity, url); }
            catch (Exception e) { throw new IllegalStateException(e); }
        });
    }

    private void load(String url) {
        appLoad(url);
        await(() -> url.equals(finishedUrl) && url.equals(url()), "page finish " + url);
    }

    private String fixture(String body) {
        String url = "https://www.ucdenver.edu/__kiosk_navigation_fixture__/" + (++sequence);
        fixtures.put(url, "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Synthetic kiosk test</title>" + body);
        return url;
    }

    private WebResourceResponse response(String content) {
        return new WebResourceResponse("text/html", "UTF-8", new ByteArrayInputStream(
                content.getBytes(StandardCharsets.UTF_8)));
    }

    private final class ObservedClient extends WebViewClient {
        private final WebViewClient delegate;
        ObservedClient(WebViewClient delegate) { this.delegate = delegate; }
        private boolean override(WebView view, String url, WebResourceRequest request) {
            boolean decision = request == null ? delegate.shouldOverrideUrlLoading(view, url)
                    : delegate.shouldOverrideUrlLoading(view, request);
            if (decision) { blocked.incrementAndGet(); preRequestBlocks.incrementAndGet(); }
            if (!allowed(url) && !decision) {
                safetyFailures.incrementAndGet();
                return true; // Test containment; the failed production decision is recorded.
            }
            return decision;
        }
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return override(view, request.getUrl().toString(), request);
        }
        @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return override(view, url, null);
        }
        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            WebResourceResponse decision = delegate.shouldInterceptRequest(view, request);
            if (request.isForMainFrame() && decision != null) {
                blocked.incrementAndGet(); preRequestBlocks.incrementAndGet();
            }
            if (decision != null) return decision;
            String url = request.getUrl().toString();
            if (request.isForMainFrame() && !allowed(url)) {
                safetyFailures.incrementAndGet();
                return response("Test containment: production failed to block this request");
            }
            if (synthetic) {
                if (request.isForMainFrame() && !fixtures.containsKey(url)) safetyFailures.incrementAndGet();
                return response(fixtures.getOrDefault(url, ""));
            }
            return null;
        }
        @Override public void onPageStarted(WebView view, String url, Bitmap icon) {
            if (!allowed(url)) blocked.incrementAndGet();
            delegate.onPageStarted(view, url, icon);
        }
        @Override public void onPageFinished(WebView view, String url) {
            delegate.onPageFinished(view, url);
            finishedUrl = url;
            finishes.incrementAndGet();
        }
        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) liveError = String.valueOf(error.getErrorCode());
            delegate.onReceivedError(view, request, error);
        }
    }

    private void observeCurrentWebView() {
        try {
            Field field = activity.getClass().getDeclaredField("webView");
            field.setAccessible(true);
            WebView current = (WebView) field.get(activity);
            if (current == web && current.getWebViewClient() instanceof ObservedClient) return;
            web = current;
            web.stopLoading();
            original = web.getWebViewClient();
            web.setWebViewClient(new ObservedClient(original));
            Field resetting = activity.getClass().getDeclaredField("resetLoading");
            resetting.setAccessible(true);
            if (synthetic && resetting.getBoolean(activity)) {
                finishedUrl = "";
                fixtures.put(home, "<title>Synthetic reset homepage</title>");
                loadApproved.invoke(activity, home);
            }
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private void approvedLink(String destination) throws Exception {
        fixtures.put(destination, "<title>Approved synthetic destination</title>");
        String source = fixture("<a id='go' href='" + TextUtils.htmlEncode(destination) + "'>Continue</a>");
        load(source);
        int before = blocked.get();
        js("document.getElementById('go').click()");
        await(() -> destination.equals(finishedUrl) && destination.equals(url()), "approved link");
        check(blocked.get() == before && visible(), "Approved link was blocked or hidden");
        pass("WebView approved link " + destination);
    }

    private void blockedLink(String destination) throws Exception {
        String source = fixture("<a id='go' href='" + TextUtils.htmlEncode(destination) + "'>Continue</a>");
        load(source);
        int before = preRequestBlocks.get();
        js("document.getElementById('go').click()");
        await(() -> preRequestBlocks.get() > before, "blocked link callback");
        check(source.equals(url()), "Blocked link replaced the source page");
        pass("WebView blocked link " + destination);
    }

    private void redirect(boolean meta) throws Exception {
        String bad = "https://ucdenver.edu.attacker.example/redirect-target";
        String redirect = meta ? "<meta http-equiv='refresh' content='1;url=" + bad + "'>"
                : "<script>setTimeout(function(){location.replace(" + JSONObject.quote(bad) + ")},1000)</script>";
        String source = fixture(redirect);
        int before = preRequestBlocks.get();
        load(source);
        await(() -> preRequestBlocks.get() > before, "disallowed redirect");
        check(source.equals(url()), "Disallowed redirect replaced the source page");
        pass(meta ? "WebView blocked meta-refresh redirect" : "WebView blocked JavaScript redirect");
    }

    private void post(boolean approve) throws Exception {
        String destination = approve ? "https://cm.maxient.com/__kiosk_navigation_fixture__/post"
                : "https://ucdenver.edu.attacker.example/post";
        if (approve) fixtures.put(destination, "<title>Synthetic POST destination</title>");
        String source = fixture("<form method='POST' action='" + destination
                + "'><input name='marker' value='SYNTHETIC_KIOSK_TEST'><button id='go'>Continue</button></form>");
        load(source);
        int before = preRequestBlocks.get();
        js("document.getElementById('go').click()");
        if (approve) {
            await(() -> destination.equals(finishedUrl) && destination.equals(url()), "approved POST");
            check(visible(), "Approved POST hidden");
        } else {
            await(() -> preRequestBlocks.get() > before, "disallowed POST before request");
            check(source.equals(url()) || !visible(), "Disallowed POST content remained visible");
        }
        pass("WebView " + (approve ? "allowed" : "blocked") + " synthetic POST");
        if (!approve && !allowed(url())) {
            runOnMainSync(() -> {
                int retryId = activity.getResources().getIdentifier("btn_retry", "id", activity.getPackageName());
                activity.findViewById(retryId).performClick();
            });
            check(!visible(), "Retry revealed a blocked page");
            pass("Production Retry keeps blocked content hidden");
        }
    }

    private void touchLink() throws Exception {
        CountDownLatch drawn = new CountDownLatch(1);
        runOnMainSync(() -> web.postVisualStateCallback(1, new WebView.VisualStateCallback() {
            @Override public void onComplete(long requestId) { drawn.countDown(); }
        }));
        check(drawn.await(8, TimeUnit.SECONDS), "WebView did not render the touch fixture");
        SystemClock.sleep(150);
        JSONArray point = new JSONArray(js("(function(){var r=document.getElementById('go').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2,innerWidth]})()"));
        AtomicReference<float[]> screen = new AtomicReference<>();
        runOnMainSync(() -> {
            int[] location = new int[2];
            web.getLocationOnScreen(location);
            try {
                float scale = web.getWidth() / (float) point.getDouble(2);
                screen.set(new float[]{location[0] + (float) point.getDouble(0) * scale,
                        location[1] + (float) point.getDouble(1) * scale});
            } catch (Exception e) { throw new IllegalStateException(e); }
        });
        long now = SystemClock.uptimeMillis();
        float[] xy = screen.get();
        android.view.MotionEvent down = android.view.MotionEvent.obtain(now, now,
                android.view.MotionEvent.ACTION_DOWN, xy[0], xy[1], 0);
        android.view.MotionEvent up = android.view.MotionEvent.obtain(now, now + 80,
                android.view.MotionEvent.ACTION_UP, xy[0], xy[1], 0);
        down.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
        up.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
        sendPointerSync(down);
        SystemClock.sleep(80);
        sendPointerSync(up);
        down.recycle();
        up.recycle();
        SystemClock.sleep(150);
        // Record activation even if Chromium handles the touch before its navigation callback.
        report("TOUCH_USER_ACTIVATION " + js("navigator.userActivation.hasBeenActive"));
    }

    private void testRetryBackReset() throws Exception {
        String first = fixture("<a id='go' href='https://cm.maxient.com/__kiosk_navigation_fixture__/back'>Next</a>");
        String second = "https://cm.maxient.com/__kiosk_navigation_fixture__/back";
        fixtures.put(second, "<title>Synthetic second page</title>");
        load(first);
        js("document.getElementById('go').click()");
        await(() -> second.equals(finishedUrl) && second.equals(url()), "history second page");
        int blockedBefore = blocked.get();
        runOnMainSync(() -> activity.onBackPressed());
        await(() -> blocked.get() > blockedBefore && !visible(), "skipped disallowed history blocked");
        check(!allowed(url()), "Skipped-history fixture did not exercise a disallowed target");
        pass("Production Back hides a skipped disallowed history destination");
        // A real touch establishes user activation, unlike evaluateJavascript clicks.
        String touchSource = fixture("<a id='go' style='display:block;margin:200px 50px;padding:40px' href='" + second + "'>Next</a>");
        load(touchSource);
        touchLink();
        await(() -> second.equals(finishedUrl) && second.equals(url()), "touch-driven second page");
        runOnMainSync(() -> activity.onBackPressed());
        await(() -> touchSource.equals(finishedUrl) && touchSource.equals(url()), "approved touch history Back");
        pass("Production Back returns to touch-activated approved history entry");
        int before = finishes.get();
        runOnMainSync(() -> {
            int retryId = activity.getResources().getIdentifier("btn_retry", "id", activity.getPackageName());
            activity.findViewById(retryId).performClick();
        });
        await(() -> finishes.get() > before && touchSource.equals(finishedUrl), "approved Retry");
        pass("Production Retry reloads approved URL");
        fixtures.put(home, "<title>Synthetic reset homepage</title>");
        runOnMainSync(() -> {
            try {
                Method reset = activity.getClass().getDeclaredMethod("onInactivityTimeout");
                reset.setAccessible(true);
                reset.invoke(activity);
            } catch (Exception e) { throw new IllegalStateException(e); }
        });
        await(() -> home.equals(finishedUrl) && home.equals(url()), "reset homepage");
        pass("Production reset loads approved configured homepage");
    }

    private String liveFlow() throws Exception {
        synthetic = false;
        fixtures.clear();
        finishedUrl = "";
        liveError = "";
        appLoad(home);
        for (int hop = 0; hop < 3; hop++) {
            long deadline = SystemClock.elapsedRealtime() + 25000;
            while (finishedUrl.isEmpty() && liveError.isEmpty() && SystemClock.elapsedRealtime() < deadline) {
                SystemClock.sleep(100);
            }
            report("LIVE_URL " + url());
            report("LIVE_TITLE " + js("document.title"));
            if (!liveError.isEmpty() || !visible()) return "PENDING_LOAD_ERROR_" + liveError;
            String host = Uri.parse(url()).getHost();
            if (host != null && (host.equals("cm.maxient.com") || host.endsWith(".cm.maxient.com"))) {
                return "PASS_EQUITY_TO_MAXIENT_GET_ONLY";
            }
            JSONArray links = new JSONArray(js("Array.from(document.links).filter(a=>a.href.startsWith('https://')).map(a=>({href:a.href,text:a.innerText}))"));
            String destination = null;
            for (int i = 0; i < links.length(); i++) {
                JSONObject link = links.getJSONObject(i);
                String candidate = link.getString("href");
                String candidateHost = Uri.parse(candidate).getHost();
                if (allowed(candidate) && candidateHost != null && (candidateHost.equals("cm.maxient.com")
                        || candidateHost.endsWith(".cm.maxient.com"))) { destination = candidate; break; }
            }
            if (destination == null && hop == 0) {
                for (int i = 0; i < links.length(); i++) {
                    JSONObject link = links.getJSONObject(i);
                    String candidate = link.getString("href");
                    if (allowed(candidate) && candidate.contains("/equity/")
                            && link.getString("text").toLowerCase(java.util.Locale.ROOT).contains("report")) {
                        destination = candidate; break;
                    }
                }
            }
            if (destination == null) return "PENDING_NO_APPROVED_MAXIENT_LINK";
            finishedUrl = "";
            String next = destination;
            js("Array.from(document.links).find(a=>a.href===" + JSONObject.quote(next) + ").click()");
        }
        return "PENDING_LIVE_FLOW_NOT_REACHED";
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            KeyguardManager keyguard = getTargetContext().getSystemService(KeyguardManager.class);
            check(keyguard != null && !keyguard.isKeyguardLocked(), "Unlock the designated tablet before UI testing");
            Class<?> policyClass = getTargetContext().getClassLoader().loadClass("com.example.webkiosk.NavigationPolicy");
            policy = policyClass.getMethod("isAllowed", String.class);
            home = (String) policyClass.getField("START_URL").get(null);
            NavigationPolicyTest.main(new String[0]);
            pass("All navigation policy cases on Android runtime");
            getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
                    .setOnAccessibilityEventListener(event -> {
                        if (event.getEventType() == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED
                                && event.getText().toString().contains("Navigation blocked")) toasts.incrementAndGet();
                    });
            Intent intent = new Intent().setClassName("com.example.webkiosk", "com.example.webkiosk.MainActivity");
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = startActivitySync(intent);
            loadApproved = activity.getClass().getDeclaredMethod("loadApprovedUrl", String.class);
            loadApproved.setAccessible(true);
            runOnMainSync(() -> {
                try {
                    keepScreenWasOn = (activity.getWindow().getAttributes().flags
                            & android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) != 0;
                    activity.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    observeCurrentWebView();
                } catch (Exception e) { throw new IllegalStateException(e); }
            });
            await(() -> home.equals(finishedUrl) && visible(), "fresh-session synthetic homepage");
            approvedLink("https://ucdenver.edu/__kiosk_navigation_fixture__/root");
            approvedLink("https://a.b.ucdenver.edu/__kiosk_navigation_fixture__/subdomain");
            approvedLink("https://cm.maxient.com/__kiosk_navigation_fixture__/report");
            approvedLink("https://forms.cm.maxient.com/__kiosk_navigation_fixture__/subdomain");
            for (String bad : new String[]{"https://attackerucdenver.edu/", "https://ucdenver.edu.attacker.example/",
                    "https://cm.maxient.com.attacker.example/", "https://ucdenver.edu@attacker.example/",
                    "http://www.ucdenver.edu/"}) blockedLink(bad);
            redirect(false);
            redirect(true);
            post(true);
            post(false);
            testRetryBackReset();
            runOnMainSync(() -> check(original.shouldOverrideUrlLoading(web, "http://www.ucdenver.edu/"),
                    "Legacy callback accepted HTTP"));
            pass("Production legacy callback blocks HTTP on Android runtime");
            await(() -> toasts.get() > 0, "visible Navigation blocked accessibility event");
            pass("Navigation blocked Toast observed through accessibility event");
            check(safetyFailures.get() == 0, "Test containment caught " + safetyFailures.get() + " unsafe production decisions");
            result.putString("session3_status", "PASS");
            result.putInt("session3_checks", passed);
            String live = arguments.getString("runLiveFlow", "false").equals("true") ? liveFlow() : "NOT_REQUESTED";
            result.putString("session3_live_status", live);
            report("LIVE_FLOW_STATUS " + live);
            if (web != null) runOnMainSync(() -> {
                web.setWebViewClient(original);
                if (!keepScreenWasOn) activity.getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
            finish(Activity.RESULT_OK, result);
        } catch (Throwable failure) {
            report("FAIL " + failure.toString());
            if (web != null) report("FAIL_HISTORY " + history());
            result.putString("session3_status", "FAIL");
            result.putString("session3_failure", failure.toString());
            if (web != null && original != null) runOnMainSync(() -> {
                web.setWebViewClient(original);
                if (!keepScreenWasOn) activity.getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
