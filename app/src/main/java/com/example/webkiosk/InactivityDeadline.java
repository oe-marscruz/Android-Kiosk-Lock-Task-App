package com.example.webkiosk;

/** A session deadline on a monotonic clock that includes device sleep. */
public final class InactivityDeadline {
    public interface Clock {
        long now();
    }

    private final Clock clock;
    private final long timeoutMs;
    private long lastInteraction;

    public InactivityDeadline(Clock clock, long timeoutMs) {
        if (timeoutMs <= 0) throw new IllegalArgumentException("Timeout must be positive");
        this.clock = clock;
        this.timeoutMs = timeoutMs;
        startSession();
    }

    public void startSession() {
        lastInteraction = clock.now();
    }

    public long remainingMs() {
        long elapsed = clock.now() - lastInteraction;
        // A clock discontinuity has no trustworthy session age.
        if (elapsed < 0 || elapsed >= timeoutMs) return 0;
        return timeoutMs - elapsed;
    }

    public boolean recordInteraction() {
        if (remainingMs() == 0) return false;
        lastInteraction = clock.now();
        return true;
    }
}
