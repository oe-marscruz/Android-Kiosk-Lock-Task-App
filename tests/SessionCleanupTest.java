package com.example.webkiosk;

import java.util.ArrayList;
import java.util.List;

public final class SessionCleanupTest {
    private static int checks;
    private static void check(boolean result, String label) {
        if (!result) throw new AssertionError(label);
        checks++;
    }

    public static void main(String[] args) {
        SessionCleanup cleanup = new SessionCleanup();
        List<Runnable> callbacks = new ArrayList<>();
        List<String> opened = new ArrayList<>();
        cleanup.request(callbacks::add, () -> opened.add("first"));
        check(opened.isEmpty(), "no request before asynchronous deletion completes");
        cleanup.request(callbacks::add, () -> opened.add("superseded"));
        SessionCleanup.Request latest = cleanup.request(callbacks::add, () -> opened.add("latest"));
        check(callbacks.size() == 1, "global cleanup never overlaps across activities");
        callbacks.get(0).run();
        check(opened.isEmpty() && callbacks.size() == 2, "stale callback cannot open a page");
        callbacks.get(0).run();
        check(opened.isEmpty() && callbacks.size() == 2, "duplicate stale callback is ignored");
        callbacks.get(1).run();
        check(opened.equals(List.of("latest")), "only latest request opens after its own deletion");
        callbacks.get(1).run();
        check(opened.size() == 1, "duplicate completion cannot open twice");

        SessionCleanup.Request destroyed = cleanup.request(callbacks::add, () -> opened.add("destroyed"));
        destroyed.cancel();
        callbacks.get(2).run();
        check(opened.size() == 1, "destroyed owner never opens content");
        cleanup.request(done -> { throw new IllegalStateException("synthetic deletion failure"); },
                () -> opened.add("failed"));
        check(opened.size() == 1, "cleanup failure stays closed");
        cleanup.request(Runnable::run, () -> opened.add("retry"));
        check(opened.equals(List.of("latest", "retry")), "fresh request can recover after failure");
        latest.cancel();
        cleanup.request(callbacks::add, () -> opened.add("next activity"));
        callbacks.get(3).run();
        check(opened.contains("next activity"), "old owner cancellation cannot cancel a newer request");

        cleanup.request(done -> {
            cleanup.request(callbacks::add, () -> opened.add("reentrant"));
            done.run();
        }, () -> opened.add("obsolete"));
        check(!opened.contains("obsolete"), "reentrant request supersedes the current owner");
        callbacks.get(4).run();
        check(opened.contains("reentrant"), "reentrant cleanup remains serialized");
        System.out.println("Passed " + checks + " session cleanup checks");
    }
}
