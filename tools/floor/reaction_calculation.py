"""Exact support reactions for constant-EI continuous teaching beams.

Downward load inputs, upward reactions; fixed support translations and free
rotations. EI=1 cancels from reactions. No physical deflections are reported.
"""
from fractions import Fraction
import math


def rational(value):
    if isinstance(value, Fraction):
        return value
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("A finite non-boolean number is required.")
    return Fraction(str(value))


def display(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Result exceeds JSON finite numeric range.")
    return {"value": number, "exact": str(value)}


def _solve(matrix, rhs):
    n = len(rhs)
    a = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for i in range(n):
        pivot = next((j for j in range(i, n) if a[j][i]), None)
        if pivot is None:
            raise ValueError("Singular beam support system.")
        a[i], a[pivot] = a[pivot], a[i]
        divisor = a[i][i]
        a[i] = [v / divisor for v in a[i]]
        for j in range(n):
            if j != i:
                factor = a[j][i]
                a[j] = [v-factor*w for v, w in zip(a[j], a[i])]
    return [row[-1] for row in a]


def _shape(length, position):
    r = position / length
    return [1-3*r*r+2*r**3, length*(r-2*r*r+r**3),
            3*r*r-2*r**3, length*(-r*r+r**3)]


def _integral(length, position):
    r = position / length
    return [length*(r-r**3+r**4/2), length**2*(r*r/2-2*r**3/3+r**4/4),
            length*(r**3-r**4/2), length**2*(-r**3/3+r**4/4)]


def beam_reactions(spans_m, points=(), udls=()):
    """points=(global x m,P kN); udls=(start m,end m,q kN/m)."""
    spans = [rational(v) for v in spans_m]
    if not 1 <= len(spans) <= 3 or min(spans) <= 0:
        raise ValueError("One to three positive spans required.")
    xs = [Fraction(0)]
    for length in spans:
        xs.append(xs[-1]+length)
    ps = [(rational(x), rational(p)) for x, p in points]
    qs = [(rational(a), rational(b), rational(q)) for a, b, q in udls]
    if any(not 0 <= x <= xs[-1] or p < 0 for x, p in ps):
        raise ValueError("Point load outside beam or negative downward load.")
    if any(not 0 <= a < b <= xs[-1] or q < 0 for a, b, q in qs):
        raise ValueError("Distributed load outside beam or negative load.")
    size = 2*len(xs)
    k = [[Fraction(0) for _ in range(size)] for _ in range(size)]
    f = [Fraction(0) for _ in range(size)]
    elements = []
    for i, length in enumerate(spans):
        local = [[12,6*length,-12,6*length],
                 [6*length,4*length**2,-6*length,2*length**2],
                 [-12,-6*length,12,-6*length],
                 [6*length,2*length**2,-6*length,4*length**2]]
        local = [[v/length**3 for v in row] for row in local]
        load = [Fraction(0)]*4
        # A point exactly on a support belongs to its right element (last to left).
        for x, p in ps:
            if xs[i] <= x < xs[i+1] or i == len(spans)-1 and x == xs[-1]:
                load = [v-p*n for v,n in zip(load,_shape(length,x-xs[i]))]
        for a,b,q in qs:
            left,right = max(a,xs[i]),min(b,xs[i+1])
            if left < right:
                ia,ib = _integral(length,left-xs[i]),_integral(length,right-xs[i])
                load = [v-q*(y-x) for v,x,y in zip(load,ia,ib)]
        ids = list(range(2*i,2*i+4))
        for j, gj in enumerate(ids):
            f[gj] += load[j]
            for h, gh in enumerate(ids):
                k[gj][gh] += local[j][h]
        elements.append((ids,local,load))
    free = list(range(1,size,2))
    rotation = _solve([[k[i][j] for j in free] for i in free],[f[i] for i in free])
    u = [Fraction(0)]*size
    for i,v in zip(free,rotation):
        u[i] = v
    residual = [sum(a*b for a,b in zip(row,u))-v for row,v in zip(k,f)]
    reactions = residual[::2]
    ends = []
    for ids,local,load in elements:
        ef = [sum(a*u[b] for a,b in zip(row,ids))-v for row,v in zip(local,load)]
        ends.append([-ef[1],ef[3]])
    force = sum(reactions)-sum(p for x,p in ps)-sum(q*(b-a) for a,b,q in qs)
    moment = sum(r*x for r,x in zip(reactions,xs))-sum(p*x for x,p in ps)-sum(q*(b*b-a*a)/2 for a,b,q in qs)
    if force or moment or any(residual[i] for i in free):
        raise ArithmeticError("Exact equilibrium failed.")
    return {"reactions":reactions,"support_x_m":xs,"end_moments":ends,
            "force_residual":force,"moment_residual":moment}


def wall_weight(wall, gamma_g):
    length = (rational(wall['end_mm'])-rational(wall['start_mm']))/1000
    area = length*rational(wall['height_mm'])/1000
    area -= sum(rational(o['width_mm'])*rational(o['height_mm'])/1000000 for o in wall['openings'])
    per_area = rational(wall['thickness_mm'])*rational(wall['density_kN_m3'])/1000
    per_area += sum(rational(f['thickness_mm'])*rational(f['density_kN_m3'])/1000 for f in wall['finishes'])
    weight = area*per_area+rational(wall['additional_weight_kN'])
    q = weight/length
    return {"net_area_m2":display(area),"characteristic_weight_kN":display(weight),
            "characteristic_q_kN_m":display(q),"design_weight_kN":display(weight*rational(gamma_g)),
            "design_q_kN_m":display(q*rational(gamma_g))}
