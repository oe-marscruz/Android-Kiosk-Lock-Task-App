package com.example.webkiosk;

import java.nio.charset.StandardCharsets;

final class WifiInput {
    private WifiInput() { }

    static boolean validSsid(String ssid) {
        return !ssid.isEmpty() && ssid.getBytes(StandardCharsets.UTF_8).length <= 32;
    }

    static boolean validPassword(String password) {
        return password.isEmpty() || (password.length() >= 8 && password.length() <= 63
                && password.matches("[\\x20-\\x7E]+"));
    }

    static String visibleSsid(String ssid) {
        if (ssid == null) return null;
        if (ssid.length() > 1 && ssid.startsWith("\"") && ssid.endsWith("\"")) {
            ssid = ssid.substring(1, ssid.length() - 1);
        }
        return ssid.isEmpty() || "<unknown ssid>".equalsIgnoreCase(ssid) ? null : ssid;
    }
}
