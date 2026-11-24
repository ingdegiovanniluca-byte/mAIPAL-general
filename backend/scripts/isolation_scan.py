"""Static scan of the API for tenant isolation: for every endpoint, the database reads/writes whose filter uses an id that
comes from the request (path parameter or body field) WITHOUT anything tying it to the current user / organization.
Prints the suspicious ones for manual review."""
import ast, sys, re

def scan(src_path):
    """-> [(method, path, function, collection, op, keys, line, has_current)]"""
    tree = ast.parse(open(src_path).read())
    return _scan(tree)


def _scan(tree):
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    SCOPE_KEYS = {"user_id", "org_id", "tenant_id", "owner_user_id", "collection_id", "commessa_id", "org_ids", "author_user_id",
                  "tenant_kb", "shared_with", "item_id"}
    DBOPS = {"find_one", "find", "update_one", "update_many", "delete_one", "delete_many", "find_one_and_update", "count_documents",
             "replace_one", "aggregate"}


    def route_of(fn):
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "api_router":
                path = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else "?"
                return d.func.attr.upper(), path
        return None


    def names_in(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | \
               {f"{n.value.id}.{n.attr}" for n in ast.walk(node) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}


    out = []
    for fn in funcs.values():
        r = route_of(fn)
        if not r:
            continue
        method, path = r
        params = set(re.findall(r"{(\w+)}", path))
        body_param = [a.arg for a in fn.args.args if a.arg in ("payload", "body", "data", "p")]
        tainted = set(params) | {f"{b}." for b in body_param}
        has_current = any(a.arg == "current" for a in fn.args.args + fn.args.kwonlyargs)
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in DBOPS):
                continue
            tgt = call.func.value
            if not (isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "db"):
                continue
            if not call.args or not isinstance(call.args[0], ast.Dict):
                continue
            flt = call.args[0]
            keys = [k.value for k in flt.keys if isinstance(k, ast.Constant)]
            spread = any(k is None for k in flt.keys)   # **_visible_query(...) etc.
            uses = names_in(flt)
            hit = [t for t in tainted if (t in uses) or (t.endswith(".") and any(u.startswith(t) for u in uses))]
            if not hit:
                continue
            if spread or SCOPE_KEYS & set(keys):
                continue
            out.append((method, path, fn.name, tgt.attr, call.func.attr, keys, call.lineno, has_current))

    return out


if __name__ == "__main__":
    out = scan(sys.argv[1])
    for m, p, f, coll, op, keys, ln, cur in sorted(out, key=lambda x: (x[1], x[0])):
        print(f"{ln:6d} {m:6s} {p:55s} {f:38s} db.{coll}.{op} {keys}{'' if cur else '  (no current user!)'}")
    print(len(out), "suspicious db calls", file=sys.stderr)
