package com.example.webkiosk;

public final class InactivityDeadlineTest {
    private static long now;
    private static int checks;

    private static void expect(long expected, long actual, String label) {
        checks++;
        if (expected != actual) throw new AssertionError(label + ": " + actual + " != " + expected);
    }

    public static void main(String[] args) {
        now = 1000;
        InactivityDeadline timer = new InactivityDeadline(() -> now, 180000);
        expect(180000, timer.remainingMs(), "fresh session");
        now += 179999;
        expect(1, timer.remainingMs(), "foreground just before expiry");
        expect(1, timer.remainingMs(), "pause/resume must not extend deadline");
        now++;
        expect(0, timer.remainingMs(), "exact threshold");
        expect(0, timer.recordInteraction() ? 1 : 0, "late input cannot revive session");
        now += 600000;
        expect(0, timer.remainingMs(), "long background or screen sleep");
        timer.startSession();
        expect(180000, timer.remainingMs(), "completed reset starts next session");
        now += 120000;
        expect(1, timer.recordInteraction() ? 1 : 0, "genuine input accepted");
        expect(180000, timer.remainingMs(), "input extends deadline");
        now += 179990;
        expect(10, timer.remainingMs(), "schedule remaining interval on resume");
        now += 10;
        expect(0, timer.remainingMs(), "remaining interval expires");
        timer.startSession();
        now--;
        expect(0, timer.remainingMs(), "clock regression fails closed");
        InactivityDeadline recreated = new InactivityDeadline(() -> now, 180000);
        expect(180000, recreated.remainingMs(), "new instance has independent cleared session deadline");
        try {
            new InactivityDeadline(() -> now, 0);
            throw new AssertionError("zero timeout accepted");
        } catch (IllegalArgumentException expected) { checks++; }
        System.out.println(checks + " inactivity deadline checks passed");
    }
}
