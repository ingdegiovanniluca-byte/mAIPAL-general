package it.maipal.watch

import android.content.Context

/** What the watch remembers: its session token and the last agent used. */
class Store(ctx: Context) {
    private val p = ctx.getSharedPreferences("maipal", Context.MODE_PRIVATE)

    var token: String?
        get() = p.getString("token", null)
        set(v) = p.edit().putString("token", v).apply()

    var name: String
        get() = p.getString("name", "") ?: ""
        set(v) = p.edit().putString("name", v).apply()

    var agent: String
        get() = p.getString("agent", AGENTS.first().id) ?: AGENTS.first().id
        set(v) = p.edit().putString("agent", v).apply()
}
