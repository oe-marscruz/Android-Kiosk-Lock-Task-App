package com.example.webkiosk;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.content.Context;
import android.graphics.Bitmap;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebViewDatabase;
import android.widget.Button;
import android.widget.Toast;

import java.io.ByteArrayInputStream;

public class MainActivity extends Activity {
    private volatile WebView webView;
    private View errorLayout;
    private Button btnRetry;
    private View sessionCover;
    private boolean resumed;
    private volatile boolean destroyed;
    private volatile boolean resetting;
    private volatile boolean resetLoading;
    private volatile boolean exiting;
    private static final SessionCleanup SESSION_CLEANUP = new SessionCleanup();
    private SessionCleanup.Request cleanupRequest;
    private boolean pageFailed;
    private boolean isDarkMode = false;
    private boolean mInLockTask = false;

    private static final String START_URL = NavigationPolicy.START_URL;
    private static final String PREFS_NAME = "kiosk_prefs";
    private static final String KEY_DARK_MODE = "dark_mode";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Prevent screen capture & recording for FERPA privacy compliance
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        setContentView(R.layout.activity_main);

        // Restore dark mode preference
        android.content.SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        isDarkMode = prefs.getBoolean(KEY_DARK_MODE, false);

        webView = findViewById(R.id.web_view);
        errorLayout = findViewById(R.id.error_layout);
        btnRetry = findViewById(R.id.btn_retry);
        sessionCover = findViewById(R.id.session_cover);

        btnRetry.setOnClickListener(v -> {
            if (!ensureSessionActive()) return;
            pageFailed = false;
            updateContentVisibility();
            loadApprovedUrl(START_URL);
        });

        beginFreshSession();
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false); // Disable DOM storage caching
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        // FERPA Hardening: disable caching, enforce HTTPS mixed content restrictions
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSaveFormData(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setDatabaseEnabled(false);

        applyDarkMode();

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !acceptsRequests(view) || blockNavigation(request.getUrl().toString());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return !acceptsRequests(view) || blockNavigation(url);
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (!acceptsRequests(view)) return blockedResponse();
                // POST and app-initiated main-frame requests can skip the override callback.
                if (request.isForMainFrame() && !NavigationPolicy.isAllowed(request.getUrl().toString())) {
                    runOnUiThread(() -> { if (acceptsRequests(view)) showNavigationBlocked(); });
                    return blockedResponse();
                }
                return null;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                if (!acceptsRequests(view)) return;
                // Redirects that skip interception still receive the same policy check.
                if (blockNavigation(url)) {
                    view.stopLoading();
                    pageFailed = true;
                    finishResetLoad();
                    updateContentVisibility();
                    return;
                }
                super.onPageStarted(view, url, favicon);
                pageFailed = false;
                updateContentVisibility();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!acceptsRequests(view)) return;
                if (!NavigationPolicy.isAllowed(url)) return;
                // Reset redirects cannot leave intermediate entries usable via Back.
                if (resetLoading || pageFailed) view.clearHistory();
                finishResetLoad();
                updateContentVisibility();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                         WebResourceError error) {
                // Gracefully handle page load errors with native layout
                if (request.isForMainFrame()) {
                    if (!acceptsRequests(view)) return;
                    pageFailed = true;
                    view.clearHistory();
                    finishResetLoad();
                    updateContentVisibility();
                }
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView view, int code, String description, String url) {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M && acceptsRequests(view)) {
                    pageFailed = true;
                    view.clearHistory();
                    finishResetLoad();
                    updateContentVisibility();
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                if (request.isForMainFrame() && acceptsRequests(view)) {
                    pageFailed = true;
                    view.clearHistory();
                    finishResetLoad();
                    updateContentVisibility();
                }
            }
        });

    }

    @Override
    protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        beginFreshSession();
    }

    private boolean acceptsRequests(WebView view) {
        return !destroyed && !exiting && view == webView && (!resetting || resetLoading);
    }

    private static WebResourceResponse blockedResponse() {
        return new WebResourceResponse("text/plain", "UTF-8", 403, "Forbidden",
                java.util.Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
    }

    // ========== Fullscreen ==========

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            enterFullscreen();
        }
    }

    private void enterFullscreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars()
                        | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            webView.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        }
    }

    // ========== Dark Mode ==========

    @SuppressWarnings("deprecation")
    private void applyDarkMode() {
        WebSettings settings = webView.getSettings();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            settings.setAlgorithmicDarkeningAllowed(isDarkMode);
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            settings.setForceDark(isDarkMode
                    ? WebSettings.FORCE_DARK_ON
                    : WebSettings.FORCE_DARK_OFF);
        }
    }

    // ========== Navigation ==========

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (!ensureSessionActive()) return true;
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (webView.canGoBack()) {
                goBackIfApproved();
            } else {
                exitToHome();
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        if (!ensureSessionActive()) return;
        if (webView.canGoBack()) {
            goBackIfApproved();
        } else {
            exitToHome();
        }
    }

    private void showNavigationBlocked() {
        Toast.makeText(this, "Navigation blocked: only approved HTTPS sites are allowed.",
                Toast.LENGTH_SHORT).show();
    }

    private boolean blockNavigation(String url) {
        if (NavigationPolicy.isAllowed(url)) return false;
        showNavigationBlocked();
        return true;
    }

    private void loadApprovedUrl(String url) {
        if (!blockNavigation(url)) webView.loadUrl(url);
    }

    private void goBackIfApproved() {
        android.webkit.WebBackForwardList history = webView.copyBackForwardList();
        int previous = history.getCurrentIndex() - 1;
        if (previous >= 0 && !blockNavigation(history.getItemAtIndex(previous).getUrl())) {
            webView.goBack();
        }
    }

    private void exitToHome() {
        if (destroyed || exiting) return;
        exiting = true;
        Toast.makeText(this, "Returning to home screen...", Toast.LENGTH_SHORT).show();
        // Exit can supersede a reset that is still deleting cookies or loading home.
        if (resetting && !resetLoading) return;
        beginReset();
    }

    private void returnToHome() {
        android.content.Intent homeIntent = new android.content.Intent(
                android.content.Intent.ACTION_MAIN);
        homeIntent.addCategory(android.content.Intent.CATEGORY_HOME);
        homeIntent.setFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                | android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK);

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                android.app.ActivityOptions options = android.app.ActivityOptions.makeBasic();
                options.setLockTaskEnabled(true);
                try {
                    startActivity(homeIntent, options.toBundle());
                } catch (RuntimeException failure) {
                    startActivity(homeIntent);
                }
            } else {
                startActivity(homeIntent);
            }
            finish();
        } catch (RuntimeException failure) {
            // Keep the cleared activity covered if the configured Home cannot open.
            Toast.makeText(this, "Could not open the home screen.", Toast.LENGTH_LONG).show();
        }
    }

    // ========== FERPA Session & Inactivity Handling ==========

    private static final long INACTIVITY_TIMEOUT_MS = 180000; // 3 minutes
    private final InactivityDeadline inactivityDeadline =
            new InactivityDeadline(SystemClock::elapsedRealtime, INACTIVITY_TIMEOUT_MS);
    private final Handler inactivityHandler = new Handler(Looper.getMainLooper());
    private final Runnable inactivityRunnable = () -> {
        if (ensureSessionActive()) scheduleInactivityCheck();
    };

    @Override
    public void onUserInteraction() {
        super.onUserInteraction();
        if (ensureSessionActive() && inactivityDeadline.recordInteraction()) {
            scheduleInactivityCheck();
        }
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        if (!ensureSessionActive()) return true;
        return super.dispatchTouchEvent(event);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (!ensureSessionActive()) return true;
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if (!ensureSessionActive()) return true;
        onUserInteraction();
        return super.dispatchGenericMotionEvent(event);
    }

    @Override
    public boolean dispatchTrackballEvent(MotionEvent event) {
        if (!ensureSessionActive()) return true;
        return super.dispatchTrackballEvent(event);
    }

    private void scheduleInactivityCheck() {
        stopInactivityTimer();
        if (resumed && !resetting && !destroyed) {
            // Handler uses uptime; recheck the sleep-inclusive deadline on every resume/input.
            inactivityHandler.postDelayed(inactivityRunnable, inactivityDeadline.remainingMs());
        }
    }

    private void stopInactivityTimer() {
        inactivityHandler.removeCallbacks(inactivityRunnable);
    }

    private boolean ensureSessionActive() {
        if (destroyed || !resumed || resetting || exiting) return false;
        if (inactivityDeadline.remainingMs() == 0) {
            onInactivityTimeout();
            return false;
        }
        return true;
    }

    private void updateContentVisibility() {
        boolean active = ensureSessionActive();
        sessionCover.setVisibility(active ? View.GONE : View.VISIBLE);
        webView.setVisibility(active && !pageFailed ? View.VISIBLE : View.INVISIBLE);
        webView.setEnabled(active);
        webView.setImportantForAccessibility(active ? View.IMPORTANT_FOR_ACCESSIBILITY_YES
                : View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        errorLayout.setVisibility(active && pageFailed ? View.VISIBLE : View.GONE);
    }

    private void onInactivityTimeout() {
        Toast.makeText(this, "Session reset due to inactivity", Toast.LENGTH_SHORT).show();
        beginFreshSession();
    }

    private void beginFreshSession() {
        if (destroyed || resetting || exiting) return;
        beginReset();
    }

    private void beginReset() {
        resetting = true;
        resetLoading = false;
        stopInactivityTimer();
        updateContentVisibility();
        // Retire the renderer before touching shared cookies/storage. It cannot repopulate
        // them or issue a late request while asynchronous deletion is in progress.
        WebView previous = webView;
        ViewGroup parent = (ViewGroup) previous.getParent();
        int index = parent.indexOfChild(previous);
        ViewGroup.LayoutParams layout = previous.getLayoutParams();
        retireWebView(previous);
        webView = new WebView(this);
        webView.setId(R.id.web_view);
        webView.setContentDescription(getString(R.string.web_view_description));
        webView.setSaveEnabled(false);
        webView.setSaveFromParentEnabled(false);
        webView.setVisibility(View.INVISIBLE);
        webView.setEnabled(false);
        webView.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        parent.addView(webView, index, layout);
        cleanupRequest = SESSION_CLEANUP.request(this::clearSessionData, () -> {
            if (destroyed) return;
            if (exiting) {
                returnToHome();
                return;
            }
            CookieManager.getInstance().setAcceptCookie(true);
            configureWebView();
            if (!resumed) webView.onPause();
            pageFailed = false;
            resetLoading = true;
            loadApprovedUrl(START_URL);
        });
    }

    private void retireWebView(WebView previous) {
        previous.setEnabled(false);
        previous.setVisibility(View.INVISIBLE);
        previous.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        previous.getSettings().setBlockNetworkLoads(true);
        previous.getSettings().setJavaScriptEnabled(false);
        previous.stopLoading();
        previous.clearCache(true);
        previous.clearHistory();
        previous.clearFormData();
        previous.clearSslPreferences();
        if (previous.getParent() != null) ((ViewGroup) previous.getParent()).removeView(previous);
        previous.removeAllViews();
        previous.destroy();
    }

    private void finishResetLoad() {
        if (!resetting || !resetLoading) return;
        resetting = false;
        resetLoading = false;
        inactivityDeadline.startSession();
        scheduleInactivityCheck();
    }

    @SuppressWarnings("deprecation")
    private void clearSessionData(Runnable completed) {
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(false);
        WebViewDatabase database = WebViewDatabase.getInstance(getApplicationContext());
        database.clearFormData();
        database.clearHttpAuthUsernamePassword();
        database.clearUsernamePassword();
        WebStorage storage = WebStorage.getInstance();
        storage.deleteAllData();
        cookieManager.removeAllCookies(removed -> {
            cookieManager.flush();
            // False can mean there were no cookies; inspect the resulting store instead.
            if (cookieManager.hasCookies()) return;
            storage.getOrigins(origins -> {
                if (origins != null && origins.isEmpty()) completed.run();
            });
        });
    }

    // ========== Lifecycle ==========

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        updateContentVisibility();
        if (!resetting || resetLoading) webView.onResume();
        scheduleInactivityCheck();
        if (!mInLockTask) {
            DevicePolicyManager dpm = (DevicePolicyManager)
                    getSystemService(Context.DEVICE_POLICY_SERVICE);
            if (dpm.isLockTaskPermitted(getPackageName())) {
                try {
                    startLockTask();
                    mInLockTask = true;
                } catch (Exception e) {
                    // Already in lock task or permission issue — safe to ignore
                }
            }
        }
    }

    @Override
    protected void onPause() {
        resumed = false;
        stopInactivityTimer();
        updateContentVisibility();
        // Pause WebView to reduce memory pressure
        try {
            webView.onPause();
        } catch (Exception ignored) {}
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        stopInactivityTimer();
        if (cleanupRequest != null) cleanupRequest.cancel();
        // Do not enqueue global deletion here: a newer activity may already be using
        // the shared store. Fresh creation always cleans before its first request.
        if (webView != null) {
            retireWebView(webView);
            webView = null;
        }
        super.onDestroy();
    }
}
