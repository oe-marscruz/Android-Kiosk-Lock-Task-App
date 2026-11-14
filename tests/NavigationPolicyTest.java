package com.example.webkiosk;

public final class NavigationPolicyTest {
    private static int cases;
    private static int failures;

    private static void expect(boolean allowed, String url) {
        cases++;
        boolean actual = NavigationPolicy.isAllowed(url);
        if (actual != allowed) {
            failures++;
            System.err.println("Expected " + (allowed ? "ALLOW " : "BLOCK ") + url);
        }
    }

    public static void main(String[] args) {
        cases = 0;
        failures = 0;
        expect(true, NavigationPolicy.START_URL);
        String[] approved = {
            "https://ucdenver.edu/",
            "https://www.ucdenver.edu/offices/equity",
            "https://cm.maxient.com/",
            "https://forms.cm.maxient.com/report",
            "https://a.b.ucdenver.edu/",
            "HTTPS://WWW.UCDENVER.EDU/offices/equity",
            "hTtPs://CM.MAXIENT.COM/",
            "https://ucdenver.edu./",
            "https://cm.maxient.com.:443/",
            "https://ucdenver.edu:8443/path?next=https://attacker.example/#fragment",
            "https://cm.maxient.com/form?name=synthetic%20test"
        };
        for (String url : approved) expect(true, url);
        expect(true, "https://" + "a".repeat(63) + ".ucdenver.edu/");
        String longestHost = ("a".repeat(63) + ".").repeat(3) + "b".repeat(48) + ".ucdenver.edu";
        expect(true, "https://" + longestHost + "/");
        expect(false, "https://" + "a".repeat(64) + ".ucdenver.edu/");
        expect(false, "https://a" + longestHost + "/");
        expect(false, "https://-bad.ucdenver.edu/");
        expect(false, "https://bad-.ucdenver.edu/");
        expect(false, "https://bad..ucdenver.edu/");

        String[] blocked = {
            null, "", " ",
            "https://attackerucdenver.edu/",
            "https://attackercm.maxient.com/",
            "https://ucdenver.edu.attacker.example/",
            "https://cm.maxient.com.attacker.example/",
            "https://ucdenver.edu@attacker.example/",
            "https://ucdenver.edu:443@attacker.example/",
            "https://attacker.example@ucdenver.edu/",
            "http://www.ucdenver.edu/",
            "http://cm.maxient.com/",
            "ftp://ucdenver.edu/",
            "file:///ucdenver.edu/",
            "content://ucdenver.edu/",
            "intent://ucdenver.edu/#Intent;scheme=https;end",
            "javascript:location='https://ucdenver.edu/'",
            "data:text/html,synthetic",
            "about:blank",
            "https:ucdenver.edu",
            "https:///ucdenver.edu/",
            "https://",
            "//ucdenver.edu/",
            "/offices/equity",
            "https://ucdenver.edu\\@attacker.example/",
            "https://attacker.example\\@ucdenver.edu/",
            "https://ucdenver.edu%2eattacker.example/",
            "https://%75cdenver.edu/",
            "https://ucdenver.edu/%zz",
            "https://ucdenver.edu:invalid/",
            "https://ucdenver.edu:65536/",
            "https://ucdenver.edu:0/",
            "https://bad_label.ucdenver.edu/",
            "https://ucdenver.edu../",
            "https://ucdenver.edu /",
            " https://ucdenver.edu/",
            "https://ucdenver.edu/\n",
            "https://127.0.0.1/",
            "https://[::1]/",
            "https://maxient.com/",
            "https://www.maxient.com/",
            "https://ucdenver.edu\u3002attacker.example/"
        };
        for (String url : blocked) expect(false, url);
        if (failures != 0) {
            throw new AssertionError(failures + " of " + cases + " navigation cases failed");
        }
        System.out.println("All " + cases + " navigation policy cases passed");
    }
}
