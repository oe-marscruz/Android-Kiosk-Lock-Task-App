package com.example.webkiosk;

/** Serializes process-wide browser cleanup. All calls and completions use the UI thread. */
public final class SessionCleanup {
    public interface Cleaner {
        void clear(Runnable completed);
    }

    public static final class Request {
        private final Cleaner cleaner;
        private final Runnable ready;
        private boolean cancelled;
        private boolean completed;

        private Request(Cleaner cleaner, Runnable ready) {
            this.cleaner = cleaner;
            this.ready = ready;
        }

        public void cancel() { cancelled = true; }
    }

    private Request current;
    private Request pending;

    public Request request(Cleaner cleaner, Runnable ready) {
        Request next = new Request(cleaner, ready);
        if (current != null) current.cancel();
        if (pending != null) pending.cancel();
        pending = next;
        drain();
        return next;
    }

    private void drain() {
        if (current != null || pending == null) return;
        Request request = pending;
        pending = null;
        current = request;
        try {
            request.cleaner.clear(() -> {
                if (request.completed) return;
                request.completed = true;
                current = null;
                if (!request.cancelled) request.ready.run();
                drain();
            });
        } catch (RuntimeException failure) {
            // A failed cleanup never opens content; a later fresh request can retry.
            if (!request.completed) {
                request.completed = true;
                current = null;
                drain();
            }
        }
    }
}
