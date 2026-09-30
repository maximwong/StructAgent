"""Small Euler-Bernoulli continuous-beam solver, kN and m, constant EI.

Vertical displacement and rotation at each support/load node; supports restrain
translation only. Point loads at nodes, no distributed loads inside elements.
Positive output moment = sagging. Pure Python; no third-party runtime dependency.
"""
from itertools import product


def solve_linear(a, b):
    a = [list(row) + [v] for row, v in zip(a, b)]
    n = len(b)
    for k in range(n):
        p = max(range(k, n), key=lambda i: abs(a[i][k]))
        if abs(a[p][k]) < 1e-12:
            raise ValueError("Singular beam stiffness matrix")
        a[k], a[p] = a[p], a[k]
        v = a[k][k]
        a[k] = [x / v for x in a[k]]
        for i in range(n):
            if i != k:
                f = a[i][k]
                a[i] = [x - f * y for x, y in zip(a[i], a[k])]
    return [row[-1] for row in a]


def beam(spans, loads):
    """loads: one [P_at_L/3, P_at_2L/3] list per span, downward positive."""
    if len(loads) != len(spans) or not spans or any(l <= 0 for l in spans):
        raise ValueError("Invalid spans / loads")
    xs = [0.0]
    for l in spans:
        start = xs[-1]
        xs.extend(start + l * j / 3 for j in (1, 2, 3))
    n = len(xs)
    k = [[0.0] * (2 * n) for _ in range(2 * n)]
    f = [0.0] * (2 * n)
    els = []
    for e in range(n - 1):
        l = xs[e + 1] - xs[e]
        ke = [[12, 6*l, -12, 6*l], [6*l, 4*l*l, -6*l, 2*l*l],
              [-12, -6*l, 12, -6*l], [6*l, 2*l*l, -6*l, 4*l*l]]
        ke = [[v / l**3 for v in row] for row in ke]
        dofs = [2*e, 2*e+1, 2*e+2, 2*e+3]
        for i, di in enumerate(dofs):
            for j, dj in enumerate(dofs):
                k[di][dj] += ke[i][j]
        els.append((dofs, ke))
    for s, ps in enumerate(loads):
        if len(ps) != 2:
            raise ValueError("Exactly two third-point loads per span required")
        f[2 * (3*s+1)] -= ps[0]
        f[2 * (3*s+2)] -= ps[1]
    fixed = {2 * j for j in range(0, n, 3)}
    free = [i for i in range(2*n) if i not in fixed]
    sol = solve_linear([[k[i][j] for j in free] for i in free], [f[i] for i in free])
    u = [0.0] * (2*n)
    for i, v in zip(free, sol):
        u[i] = v
    reactions = [sum(k[i][j]*u[j] for j in range(2*n))-f[i]
                 for i in sorted(fixed)]
    segments = []
    for e, (dofs, ke) in enumerate(els):
        ef = [sum(row[j]*u[dofs[j]] for j in range(4)) for row in ke]
        segments.append(dict(x0=xs[e], x1=xs[e+1], m0=-ef[1], m1=ef[3], v=ef[0]))
    return dict(segments=segments, reactions=reactions,
                equilibrium_error=sum(reactions)-sum(map(sum, loads)))


def moment(case, x):
    for s in case['segments']:
        if s['x0']-1e-9 <= x <= s['x1']+1e-9:
            return s['m0'] + s['v']*(x-s['x0'])
    raise ValueError("Position outside beam")


def envelope(spans, g, q):
    cases = []
    for mask in product((0, 1), repeat=len(spans)):
        c = beam(spans, [[g+q*on]*2 for on in mask])
        c['pattern'] = ''.join(map(str, mask))
        cases.append(c)
    env = []
    for i in range(len(cases[0]['segments'])):
        ss = [c['segments'][i] for c in cases]
        env.append(dict(x0=ss[0]['x0'], x1=ss[0]['x1'],
                        m0max=max(s['m0'] for s in ss), m0min=min(s['m0'] for s in ss),
                        m1max=max(s['m1'] for s in ss), m1min=min(s['m1'] for s in ss),
                        vmax=max(s['v'] for s in ss), vmin=min(s['v'] for s in ss)))
    return dict(cases=cases, segments=env, spans=spans)


def exact_envelope_points(cases):
    """Add case-line intersections so plotted M envelope is exact, not a chord."""
    xs = set()
    for i, s0 in enumerate(cases[0]['segments']):
        a, b = s0['x0'], s0['x1']
        xs.update((a, b))
        for j, c in enumerate(cases):
            s = c['segments'][i]
            for other in cases[j+1:]:
                t = other['segments'][i]
                if abs(s['v']-t['v']) > 1e-12:
                    x = a+(t['m0']-s['m0'])/(s['v']-t['v'])
                    if a < x < b:
                        xs.add(x)
    return [dict(x=x, maximum=max(moment(c,x) for c in cases),
                 minimum=min(moment(c,x) for c in cases)) for x in sorted(xs)]
