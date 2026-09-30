"""Validate the existing teaching model inputs; no engineering formulas live here."""
import math

# Values formerly held by app.MATERIALS, preserved verbatim.
CONCRETE_MATERIALS = {
    'C25': (11.9, 1.27), 'C30': (14.3, 1.43),
    'C35': (16.7, 1.57), 'C40': (19.1, 1.71),
}
STEEL_MATERIALS = {
    'slab': ('HPB300', 270),
    'beam': ('HRB400', 360),
    'stirrup': ('HPB300', 270),
}
_TEXT_FIELDS = {
    'materials.concrete', 'materials.slab_steel', 'materials.beam_steel',
    'materials.stirrup_steel', 'main.support_moment',
    'report.author', 'report.class_name', 'report.student_id', 'report.date',
}


def invalid(path, value, expected):
    raise ValueError(f'{path}: 输入 {value!r}；预期 {expected}')


def validate_numeric_inputs(p):
    def walk(value, path):
        if path == 'report.allow_arch':
            if type(value) is not bool:
                invalid(path, value, '布尔值 True 或 False')
        elif path in _TEXT_FIELDS:
            return
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + '.' + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f'{path}[{index}]')
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            invalid(path, value, '有限数值，不接受布尔值')

    for group in ('geometry', 'loads', 'materials', 'slab', 'secondary', 'main', 'detailing', 'report'):
        if group in p:
            walk(p[group], group)


def validate_materials(p):
    mat = p['materials']
    grade = mat.get('concrete')
    if not isinstance(grade, str) or grade not in CONCRETE_MATERIALS:
        invalid('materials.concrete', grade, ', '.join(CONCRETE_MATERIALS))

    def strength(key, expected, label):
        actual = mat.get(key)
        if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                or not math.isfinite(actual)
                or not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9)):
            invalid('materials.' + key, actual, f'{label} 对应 {expected} MPa')

    for key, expected in zip(('fc_MPa', 'ft_MPa'), CONCRETE_MATERIALS[grade]):
        strength(key, expected, grade)
    for member, (supported_grade, fy) in STEEL_MATERIALS.items():
        key = member + '_steel'
        if mat.get(key) != supported_grade:
            invalid('materials.' + key, mat.get(key), supported_grade + '（当前构造支持范围）')
        strength(member + '_fy_MPa', fy, supported_grade)


def validate_engineering_inputs(p):
    validate_numeric_inputs(p)
    validate_materials(p)
