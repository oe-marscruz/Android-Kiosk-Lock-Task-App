package com.example.webkiosk;

public final class WifiInputTest {
    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    public static void main(String[] args) {
        check(!WifiInput.validSsid(""));
        check(WifiInput.validSsid("Test network"));
        check(WifiInput.validSsid("é".repeat(16)));
        check(!WifiInput.validSsid("é".repeat(17)));
        check(WifiInput.validPassword(""));
        check(WifiInput.validPassword("12345678"));
        check(WifiInput.validPassword("a".repeat(63)));
        check(!WifiInput.validPassword("1234567"));
        check(!WifiInput.validPassword("a".repeat(64)));
        check(!WifiInput.validPassword("1234567é"));
        check(WifiInput.visibleSsid(null) == null);
        check(WifiInput.visibleSsid("<unknown ssid>") == null);
        check(WifiInput.visibleSsid("\"<unknown ssid>\"") == null);
        check("Test network".equals(WifiInput.visibleSsid("\"Test network\"")));
        System.out.println("WiFi input and SSID visibility tests passed");
    }
}
