package com.example.webkiosk;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

public final class NavigationPolicy {
    public static final String START_URL = "https://www.ucdenver.edu/offices/equity";
    private static final String[] ALLOWED_DOMAINS = {"ucdenver.edu", "cm.maxient.com"};

    private NavigationPolicy() {}

    public static boolean isAllowed(String url) {
        if (url == null) return false;
        try {
            URI uri = new URI(url);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getRawUserInfo() != null) {
                return false;
            }
            String host = uri.getHost();
            if (host == null || host.isEmpty()) return false;
            int port = uri.getPort();
            if (port != -1 && (port < 1 || port > 65535)) return false;
            host = host.toLowerCase(Locale.ROOT);
            // A single terminal dot denotes the same absolute DNS hostname.
            if (host.endsWith(".")) host = host.substring(0, host.length() - 1);
            // Android and desktop URI parsers differ in which DNS labels they accept.
            if (host.length() > 253) return false;
            for (String label : host.split("\\.", -1)) {
                if (label.isEmpty() || label.length() > 63
                        || label.charAt(0) == '-' || label.charAt(label.length() - 1) == '-') return false;
                for (int i = 0; i < label.length(); i++) {
                    char c = label.charAt(i);
                    if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && c != '-') return false;
                }
            }
            for (String domain : ALLOWED_DOMAINS) {
                if (host.equals(domain) || host.endsWith("." + domain)) return true;
            }
            return false;
        } catch (URISyntaxException e) {
            return false;
        }
    }
}
