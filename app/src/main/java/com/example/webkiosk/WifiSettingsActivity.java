package com.example.webkiosk;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkInfo;
import android.net.TransportInfo;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.net.wifi.WifiNetworkSuggestion;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * Lets a user add WiFi credentials from inside the kiosk app, e.g. when the
 * tablet has been disconnected from the network. Uses the WifiNetworkSuggestion
 * API (Android 10+) so the system handles the actual connection and prompts
 * the user to approve the network.
 */
public class WifiSettingsActivity extends Activity {

    private static final int REQ_PERMISSIONS = 1001;

    private WifiManager wifiManager;
    private TextView statusView;
    private EditText ssidInput;
    private EditText passwordInput;
    private TextView messageView;

    private final BroadcastReceiver wifiReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            updateStatus();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Prevent screen capture & recording for FERPA privacy compliance
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE);
        setContentView(R.layout.activity_wifi_settings);

        wifiManager = (WifiManager) getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);

        statusView = findViewById(R.id.status_view);
        ssidInput = findViewById(R.id.edit_ssid);
        passwordInput = findViewById(R.id.edit_password);
        messageView = findViewById(R.id.message_view);

        findViewById(R.id.btn_connect).setOnClickListener(v -> addNetwork());
        findViewById(R.id.btn_back).setOnClickListener(v -> finish());

        updateStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        IntentFilter filter = new IntentFilter();
        filter.addAction(WifiManager.WIFI_STATE_CHANGED_ACTION);
        filter.addAction(WifiManager.NETWORK_STATE_CHANGED_ACTION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(wifiReceiver, filter, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(wifiReceiver, filter);
        }
        updateStatus();
    }

    @Override
    protected void onPause() {
        super.onPause();
        try {
            unregisterReceiver(wifiReceiver);
        } catch (Exception ignored) {
        }
    }

    private void updateStatus() {
        if (wifiManager == null) {
            statusView.setText("WiFi service is unavailable. Open the tablet's Settings to check WiFi.");
            return;
        }
        try {
            if (!wifiManager.isWifiEnabled()) {
                statusView.setText("WiFi is OFF.\nTurn on WiFi in the tablet's Settings app, then return here.");
                return;
            }
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) {
                statusView.setText("WiFi is on, but connection status is unavailable. Check Settings.");
                return;
            }
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
                @SuppressWarnings("deprecation")
                NetworkInfo info = cm.getActiveNetworkInfo();
                if (info == null || !info.isConnected() || info.getType() != ConnectivityManager.TYPE_WIFI) {
                    statusView.setText("WiFi is on; no active WiFi connection is detected.");
                } else {
                    String ssid = getCurrentSsid(null);
                    statusView.setText(ssid == null ? "WiFi is connected; the network name is unavailable. Check Settings for details."
                            : "Connected to: " + ssid);
                }
                return;
            }
            Network active = cm.getActiveNetwork();
            NetworkCapabilities caps = active == null ? null : cm.getNetworkCapabilities(active);
            if (active != null && caps == null) {
                statusView.setText("WiFi is on, but connection status is unavailable. Check Settings.");
            } else if (caps == null || !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                statusView.setText("WiFi is on; no active WiFi connection is detected.");
            } else {
                String ssid = getCurrentSsid(caps);
                statusView.setText(ssid == null ? "WiFi is connected; the network name is unavailable. Check Settings for details."
                        : "Connected to: " + ssid);
            }
        } catch (SecurityException e) {
            statusView.setText("WiFi status is unavailable due to permissions. Check the tablet's Settings.");
        }
    }

    @SuppressWarnings("deprecation")
    private String getCurrentSsid(NetworkCapabilities caps) {
        String ssid = null;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            TransportInfo transportInfo = caps.getTransportInfo();
            if (transportInfo instanceof WifiInfo) {
                ssid = ((WifiInfo) transportInfo).getSSID();
            }
        }

        // Fallback for API < 31 or if ConnectivityManager returned null/unknown
        if (WifiInput.visibleSsid(ssid) == null && wifiManager != null) {
            try {
                WifiInfo info = wifiManager.getConnectionInfo();
                if (info != null) ssid = info.getSSID();
            } catch (SecurityException ignored) {
                return null;
            }
        }

        return WifiInput.visibleSsid(ssid);
    }

    private void addNetwork() {
        String ssid = ssidInput.getText().toString();
        String password = passwordInput.getText().toString();

        if (ssid.isEmpty()) {
            messageView.setText("Please enter the network name (SSID).");
            return;
        }
        if (!WifiInput.validSsid(ssid)) {
            messageView.setText("Network name must be 1 to 32 UTF-8 bytes. Check the name and try again.");
            return;
        }
        if (!WifiInput.validPassword(password)) {
            messageView.setText("For WPA2, enter an 8 to 63 character ASCII password, or leave it empty for an open network.");
            return;
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            messageView.setText("This tablet's Android version is too old to add WiFi from here.");
            return;
        }

        if (wifiManager == null) {
            messageView.setText("WiFi service is unavailable. Open the tablet's Settings to connect.");
            return;
        }

        if (!ensurePermissions()) {
            return;
        }

        try {
            WifiNetworkSuggestion.Builder builder = new WifiNetworkSuggestion.Builder().setSsid(ssid);
            if (!password.isEmpty()) {
                builder.setWpa2Passphrase(password);
            }
            List<WifiNetworkSuggestion> suggestions = new ArrayList<>();
            suggestions.add(builder.build());
            int result = wifiManager.addNetworkSuggestions(suggestions);
            if (result == WifiManager.STATUS_NETWORK_SUGGESTIONS_SUCCESS) {
                messageView.setText("Network suggestion submitted. Approve it if prompted, then check Settings to confirm connection.");
                Toast.makeText(this, "Network suggestion submitted", Toast.LENGTH_SHORT).show();
            } else if (result == WifiManager.STATUS_NETWORK_SUGGESTIONS_ERROR_ADD_DUPLICATE) {
                messageView.setText("This network is already suggested. Check Settings to confirm connection and any required approval.");
            } else {
                messageView.setText("Could not add the network. Check Settings and try again.");
            }
        } catch (IllegalArgumentException | IllegalStateException e) {
            messageView.setText("Invalid network name or password. Check the values and try again.");
        } catch (SecurityException e) {
            messageView.setText("WiFi access was denied. Check app permissions in Settings, then try again.");
        }
    }

    private boolean ensurePermissions() {
        List<String> needed = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES)
                    != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.NEARBY_WIFI_DEVICES);
            }
        } else {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                    != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.ACCESS_FINE_LOCATION);
            }
        }
        if (!needed.isEmpty()) {
            requestPermissions(needed.toArray(new String[0]), REQ_PERMISSIONS);
            messageView.setText("Please approve the permission prompt, then tap Connect again.");
            return false;
        }
        return true;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_PERMISSIONS) {
            boolean granted = grantResults.length > 0;
            for (int r : grantResults) {
                if (r != PackageManager.PERMISSION_GRANTED) {
                    granted = false;
                }
            }
            if (granted) {
                messageView.setText("Permission granted. Tap Connect again.");
                updateStatus();
            } else {
                messageView.setText("Permission denied. Allow WiFi access in app Settings or use the tablet's WiFi Settings.");
                updateStatus();
            }
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            finish();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        finish();
    }
}
