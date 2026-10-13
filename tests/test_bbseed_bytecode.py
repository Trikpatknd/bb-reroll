"""The bytecode runner (bbseed/sq/bytecode.py) on small hand-assembled functions.

The real proof that it runs the game's compiled scripts correctly is the replay of the
in-game campaign starts (test_ingame_logs.py). These tests cover the instructions those
runs do not reach (captured locals, traps, delete, ++ on slots, ...), each checked against
what sqvm.cpp does. An instruction is written as (opcode, arg0, arg1, arg2, arg3).
"""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.sq import bytecode, cnut
from bbseed.sq.runtime import SqClass, SqClosure, SqError, SqInstance, SqTable, typeof
from bbseed.sq.vm import VM

NONE = 0xFF
LOAD, LOADINT, TAILCALL, CALL, PREPCALLK, GETK, MOVE, NEWSLOT, DELETE, SET, GET, EQ, NE = (
    0x01, 0x02, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10)
ADD, SUB, MUL, DIV, MOD, BITW, RETURN, LOADNULLS, LOADBOOL, JMP, JCMP, JZ, SETOUTER, GETOUTER = (
    0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x1A, 0x1C, 0x1D, 0x1E, 0x1F, 0x20)
NEWOBJ, APPENDARRAY, COMPARITH, INC, INCL, PINC, PINCL, CMP, EXISTS, INSTANCEOF, AND, OR, NEG, NOT, BWNOT = (
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F)
CLOSURE, FOREACH, POSTFOREACH, CLONE, TYPEOF, PUSHTRAP, POPTRAP, THROW, NEWSLOTA, CLOSE = (
    0x30, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x3C)


def proto(code, literals=(), params=("this",), stacksize=10, functions=(), outers=(), defaults=(), varparams=0,
          generator=False, name="f"):
    p = cnut.Proto()
    p.sourcename, p.name = "test.nut", name
    p.literals, p.parameters = list(literals), list(params)
    p.outervalues, p.localvars, p.lineinfos = list(outers), [], [(1, 0)]
    p.defaultparams = list(defaults)
    p.code = b"".join(struct.pack("<iBBBB", a1, op, a0, a2, a3) for op, a0, a1, a2, a3 in code)
    p.functions, p.stacksize, p.bgenerator, p.varparams = list(functions), stacksize, generator, varparams
    return p


def closure(p, vm=None):
    vm = vm or VM()
    return SqClosure(bytecode.function(vm, p), None, [], vm)


def run(p, *args, this=None, vm=None):
    c = closure(p, vm)
    return c.invoke(c.vm.root if this is None else this, args)


def table(**slots):
    t = SqTable()
    for k, v in slots.items():
        t.newslot(k, v)
    return t


def test_arithmetic_and_operand_order():
    # return a - b * 2  (target = STK(arg2) op STK(arg1))
    p = proto([(LOADINT, 3, 2, 0, 0), (MUL, 3, 3, 2, 0), (SUB, 3, 3, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(p, 20, 3) == 14
    p = proto([(MOD, 3, 2, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(p, 17, 5) == 2 and run(p, -17, 5) == -2
    p = proto([(DIV, 3, 2, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(p, 7, 2) == 3 and run(p, -7, 2) == -3 and run(p, 7.0, 2) == 3.5
    with pytest.raises(SqError):
        run(p, 1, 0)
    for kind, want in ((0, 12 & 10), (2, 12 | 10), (3, 12 ^ 10), (4, 12 << 10), (5, 12 >> 1), (6, 12 >> 1)):
        p = proto([(BITW, 3, 2, 1, kind), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
        assert run(p, 12, 10 if kind < 5 else 1) == want
    assert run(proto([(NEG, 2, 1, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "a")), 5) == -5
    assert run(proto([(BWNOT, 2, 1, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "a")), 5) == -6
    assert run(proto([(NOT, 2, 1, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "a")), 0) is True
    assert run(proto([(RETURN, NONE, 0, 0, 0)])) is None


def test_integer_overflow_wraps_like_a_32_bit_int():
    p = proto([(ADD, 3, 2, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(p, 2147483647, 1) == -2147483648
    p = proto([(INCL, 1, 1, 0, 1), (RETURN, 1, 1, 0, 0)], params=("this", "a"))
    assert run(p, 2147483647) == -2147483648
    assert run(p, 1.5) == 2.5


def test_comparisons_and_jumps():
    # return a < b ? "lt" : "ge"   via JCMP (jumps when the comparison is false)
    lt = proto([(JCMP, 2, 2, 1, 3), (LOAD, 3, 0, 0, 0), (RETURN, 1, 3, 0, 0), (LOAD, 3, 1, 0, 0), (RETURN, 1, 3, 0, 0)],
               literals=("lt", "ge"), params=("this", "a", "b"))
    assert run(lt, 1, 2) == "lt" and run(lt, 2, 2) == "ge" and run(lt, 2.5, 2) == "ge"
    for kind, a, b, want in ((0, 3, 2, True), (0, 2, 2, False), (2, 2, 2, True), (3, 1, 2, True), (4, 2, 2, True),
                             (4, 3, 2, False), (5, 1, 2, -1), (5, 2, 2, 0), (5, 3, 2, 1)):
        p = proto([(CMP, 3, 2, 1, kind), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
        assert run(p, a, b) == want, (kind, a, b)
    eq_lit = proto([(EQ, 2, 0, 1, 1), (RETURN, 1, 2, 0, 0)], literals=("x",), params=("this", "a"))
    assert run(eq_lit, "x") is True and run(eq_lit, "y") is False
    ne = proto([(NE, 3, 2, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(ne, 1, 1.0) is False and run(ne, 1, "1") is True
    # JZ: null, false, 0 and 0.0 are false; "" and an empty array are not
    jz = proto([(JZ, 1, 2, 0, 0), (LOADBOOL, 2, 1, 0, 0), (RETURN, 1, 2, 0, 0), (LOADBOOL, 2, 0, 0, 0), (RETURN, 1, 2, 0, 0)],
               params=("this", "a"))
    assert [run(jz, v) for v in (None, False, 0, 0.0, "", [], 1, True)] == [False] * 4 + [True] * 4


def test_and_or_short_circuit_keep_the_deciding_value():
    # return a && b    /    return a || b
    land = proto([(AND, 3, 1, 1, 0), (MOVE, 3, 2, 0, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(land, 0, "b") == 0 and run(land, None, "b") is None and run(land, 5, "b") == "b"
    lor = proto([(OR, 3, 1, 1, 0), (MOVE, 3, 2, 0, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"))
    assert run(lor, 0, "b") == "b" and run(lor, "a", "b") == "a"


def test_post_increment_of_a_local():
    # local j = i++; return [i, j]
    p = proto([(PINCL, 2, 1, 0, 1), (NEWOBJ, 3, 2, 0, 1), (APPENDARRAY, 3, 1, 0, 0), (APPENDARRAY, 3, 2, 0, 0),
               (RETURN, 1, 3, 0, 0)], params=("this", "i"))
    assert run(p, 5) == [6, 5]
    # the same register as source and target: the incremented value is what remains (sqvm.cpp order)
    p = proto([(PINCL, 1, 1, 0, 1), (RETURN, 1, 1, 0, 0)], params=("this", "i"))
    assert run(p, 5) == 6
    p = proto([(PINCL, 2, 1, 0, 255), (RETURN, 1, 1, 0, 0)], params=("this", "i"))      # i--  (arg3 is signed)
    assert run(p, 5) == 4


def test_slots_get_set_newslot_delete_exists():
    t = table(x=10)
    # t.y <- t.x; t.x = 3; delete t.x -> returns the deleted value; "x" in t
    p = proto([(GETK, 2, 0, 1, 0), (LOAD, 3, 1, 0, 0), (NEWSLOT, NONE, 1, 3, 2), (LOAD, 4, 0, 0, 0), (LOADINT, 5, 3, 0, 0),
               (SET, 6, 1, 4, 5), (DELETE, 7, 1, 4, 0), (EXISTS, 8, 1, 4, 0), (NEWOBJ, 9, 0, 0, 1),
               (APPENDARRAY, 9, 6, 0, 0), (APPENDARRAY, 9, 7, 0, 0), (APPENDARRAY, 9, 8, 0, 0), (RETURN, 1, 9, 0, 0)],
              literals=("x", "y"), params=("this", "t"))
    assert run(p, t) == [3, 3, False]
    assert t.get("y") == 10 and "x" not in t
    with pytest.raises(SqError):
        run(proto([(LOAD, 2, 0, 0, 0), (LOADINT, 3, 1, 0, 0), (SET, NONE, 1, 2, 3), (RETURN, NONE, 0, 0, 0)],
                  literals=("nope",), params=("this", "t")), table())
    # `in` never throws: a key in null is just false
    p = proto([(LOAD, 2, 0, 0, 0), (EXISTS, 3, 1, 2, 0), (RETURN, 1, 3, 0, 0)], literals=("x",), params=("this", "t"))
    assert run(p, None) is False and run(p, table(x=1)) is True and run(p, 5) is False


def test_compound_assignment_and_increment_of_a_slot():
    # t.x += 5   -> COMPARITH: self register in the high word of arg1, value register in the low word
    p = proto([(LOAD, 2, 0, 0, 0), (LOADINT, 3, 5, 0, 0), (COMPARITH, 4, (1 << 16) | 3, 2, ord("+")), (RETURN, 1, 4, 0, 0)],
              literals=("x",), params=("this", "t"))
    t = table(x=10)
    assert run(p, t) == 15 and t.get("x") == 15
    p = proto([(LOAD, 2, 0, 0, 0), (LOADINT, 3, 4, 0, 0), (COMPARITH, 4, (1 << 16) | 3, 2, ord("*")), (RETURN, 1, 4, 0, 0)],
              literals=("x",), params=("this", "t"))
    assert run(p, t) == 60
    # ++t.x gives the new value, t.x++ the old one; t.x-- uses a negative step
    for op, step, want, left in ((INC, 1, 61, 61), (PINC, 1, 61, 62), (PINC, 255, 62, 61)):
        p = proto([(LOAD, 2, 0, 0, 0), (op, 3, 1, 2, step), (RETURN, 1, 3, 0, 0)], literals=("x",), params=("this", "t"))
        assert run(p, t) == want and t.get("x") == left


def test_this_falls_back_to_the_root_table():
    vm = VM()
    vm.root.newslot("Global", 7)
    env = table(Local=1)
    read = proto([(GETK, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], literals=("Global",))
    assert run(read, this=env, vm=vm) == 7
    # an assignment through `this` writes the root slot when `this` has none ...
    write = proto([(LOAD, 1, 0, 0, 0), (LOADINT, 2, 9, 0, 0), (SET, NONE, 0, 1, 2), (RETURN, NONE, 0, 0, 0)], literals=("Global",))
    run(write, this=env, vm=vm)
    assert vm.root.get("Global") == 9 and "Global" not in env
    # ... but a name that exists nowhere is an error, and another object's slots get no such fallback
    with pytest.raises(SqError):
        run(proto([(GETK, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], literals=("Missing",)), this=env, vm=vm)
    other = proto([(GETK, 2, 0, 1, 0), (RETURN, 1, 2, 0, 0)], literals=("Global",), params=("this", "t"))
    with pytest.raises(SqError):
        run(other, env, this=env, vm=vm)
    # this[integer] on an array `this`
    idx = proto([(LOADINT, 1, 1, 0, 0), (GET, 2, 0, 1, 0), (RETURN, 1, 2, 0, 0)])
    assert run(idx, this=[10, 20, 30], vm=vm) == 20


def test_calls_methods_and_tail_calls():
    vm = VM()
    seen = []
    callee = closure(proto([(ADD, 3, 2, 1, 0), (RETURN, 1, 3, 0, 0)], params=("this", "a", "b"), name="add"), vm)
    obj = table(add=callee, depth=None)
    vm.native("depth", lambda this: seen.append(len(vm.stack)))
    # return obj.add(4, 5)    PREPCALLK puts the function and the object (as `this`) in place
    p = proto([(PREPCALLK, 2, 0, 1, 3), (LOADINT, 4, 4, 0, 0), (LOADINT, 5, 5, 0, 0), (CALL, 2, 2, 3, 3), (RETURN, 1, 2, 0, 0)],
              literals=("add",), params=("this", "obj"))
    assert run(p, obj, vm=vm) == 9
    # a call whose result is not used, then a tail call: the caller's frame is gone while the callee runs
    inner = closure(proto([(PREPCALLK, 1, 0, 0, 2), (CALL, NONE, 1, 2, 1), (RETURN, NONE, 0, 0, 0)], literals=("depth",),
                          name="inner"), vm)
    outer = proto([(MOVE, 2, 1, 0, 0), (MOVE, 3, 0, 0, 0), (TAILCALL, 2, 2, 3, 1), (RETURN, 1, 2, 0, 0)],
                  params=("this", "fn"), name="outer")
    run(outer, inner, vm=vm)
    assert seen == [1] and vm.stack == []
    with pytest.raises(SqError):                    # wrong number of arguments
        callee.invoke(vm.root, (1,))
    with pytest.raises(SqError):                    # calling something that is not callable
        run(proto([(MOVE, 2, 0, 0, 0), (CALL, 3, 1, 2, 1), (RETURN, 1, 3, 0, 0)], params=("this", "fn")), 5, vm=vm)


def test_default_parameters_and_varargs():
    # function(a, b = <value of a register when the closure is made>)
    child = proto([(NEWOBJ, 3, 2, 0, 1), (APPENDARRAY, 3, 1, 0, 0), (APPENDARRAY, 3, 2, 0, 0), (RETURN, 1, 3, 0, 0)],
                  params=("this", "a", "b"), defaults=(1,))
    make = proto([(LOADINT, 1, 7, 0, 0), (CLOSURE, 2, 0, 0, 0), (RETURN, 1, 2, 0, 0)], functions=(child,))
    f = run(make)
    assert f.invoke(None, (1,)) == [1, 7] and f.invoke(None, (1, 2)) == [1, 2]
    with pytest.raises(SqError):
        f.invoke(None, ())
    with pytest.raises(SqError):
        f.invoke(None, (1, 2, 3))
    # function(a, ...) { return vargv }
    va = closure(proto([(RETURN, 1, 2, 0, 0)], params=("this", "a", "vargv"), varparams=1))
    assert va.invoke(None, (1,)) == [] and va.invoke(None, (1, 2, 3)) == [2, 3]
    with pytest.raises(SqError):
        va.invoke(None, ())
    infos = va.vm.lookup(va, "getinfos")
    from bbseed.sq.runtime import call
    assert call(infos, va, ()).get("parameters") == ["this", "a", "vargv", "..."]


def test_foreach_over_arrays_tables_and_strings():
    # local sum = 0; foreach (k, v in c) sum += v; return sum
    total = proto([(LOADINT, 2, 0, 0, 0), (LOADNULLS, 3, 3, 0, 0), (FOREACH, 1, 3, 3, 0), (POSTFOREACH, 1, 3, 3, 0),
                   (ADD, 2, 4, 2, 0), (JMP, 0, -4, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "c"))
    assert run(total, [1, 2, 3]) == 6 and run(total, []) == 0
    assert run(total, table(a=10, b=20)) == 30
    assert run(total, "AB") == 65 + 66
    with pytest.raises(SqError):
        run(total, 5)
    # the keys: array indices
    keys = proto([(NEWOBJ, 2, 0, 0, 1), (LOADNULLS, 3, 3, 0, 0), (FOREACH, 1, 3, 3, 0), (POSTFOREACH, 1, 3, 3, 0),
                  (APPENDARRAY, 2, 3, 0, 0), (JMP, 0, -4, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "c"))
    assert run(keys, ["x", "y"]) == [0, 1]
    assert sorted(run(keys, table(a=1, b=2))) == ["a", "b"]


def test_closures_share_a_captured_local_and_keep_it_after_the_function_returns():
    # local n = 0; local inc = function() { n = n + 1; return n }; inc(); inc(); return [n, inc]
    inc = proto([(GETOUTER, 1, 0, 0, 0), (LOADINT, 2, 1, 0, 0), (ADD, 1, 2, 1, 0), (SETOUTER, NONE, 0, 1, 0), (RETURN, 1, 1, 0, 0)],
                outers=((0, 1, "n"),), name="inc")
    outer = proto([(LOADINT, 1, 0, 0, 0), (CLOSURE, 2, 0, 0, 0), (MOVE, 4, 0, 0, 0), (CALL, NONE, 2, 4, 1),
                   (CALL, NONE, 2, 4, 1), (NEWOBJ, 5, 2, 0, 1), (APPENDARRAY, 5, 1, 0, 0), (APPENDARRAY, 5, 2, 0, 0),
                   (RETURN, 1, 5, 0, 0)], functions=(inc,))
    n, fn = run(outer)
    assert n == 2                                   # the closure wrote the function's own local
    assert fn.invoke(None, ()) == 3 and fn.invoke(None, ()) == 4      # and still has it afterwards
    # a closure that passes its own captured variable on to a closure it makes
    leaf = proto([(GETOUTER, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], outers=((1, 0, "v"),))
    mid = proto([(CLOSURE, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], outers=((0, 1, "v"),), functions=(leaf,))
    top = proto([(CLOSURE, 2, 0, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "v"), functions=(mid,))
    assert run(top, "kept").invoke(None, ()).invoke(None, ()) == "kept"


def test_a_local_declared_in_a_loop_body_is_captured_anew_each_time():
    # local fns = []; for (local i = 0; i < 3; i++) { local j = i * 10; fns.append(function() { return j }) }; return fns
    get_j = proto([(GETOUTER, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], outers=((0, 3, "j"),))
    loop = proto([(NEWOBJ, 1, 0, 0, 1), (LOADINT, 2, 0, 0, 0), (LOADINT, 5, 3, 0, 0), (LOADINT, 6, 10, 0, 0),
                  (JCMP, 5, 6, 2, 3),                 # 4: while i < 3
                  (MUL, 3, 6, 2, 0), (CLOSURE, 4, 0, 0, 0), (APPENDARRAY, 1, 4, 0, 0),
                  (CLOSE, 0, 3, 0, 0), (INCL, 2, 2, 0, 1), (JMP, 0, -7, 0, 0),
                  (RETURN, 1, 1, 0, 0)], functions=(get_j,))
    assert [f.invoke(None, ()) for f in run(loop)] == [0, 10, 20]


def test_try_catch():
    # try { throw x } catch (e) { return e }   /   try { } catch (e) { }; return "fine"
    thrown = proto([(PUSHTRAP, 2, 3, 0, 0), (THROW, 1, 0, 0, 0), (POPTRAP, 1, 0, 0, 0), (JMP, 0, 1, 0, 0),
                    (RETURN, 1, 2, 0, 0), (LOAD, 3, 0, 0, 0), (RETURN, 1, 3, 0, 0)], literals=("fine",), params=("this", "x"))
    assert run(thrown, "boom") == "boom"
    quiet = proto([(PUSHTRAP, 2, 2, 0, 0), (POPTRAP, 1, 0, 0, 0), (JMP, 0, 1, 0, 0), (RETURN, 1, 2, 0, 0),
                   (LOAD, 3, 0, 0, 0), (RETURN, 1, 3, 0, 0)], literals=("fine",))
    assert run(quiet) == "fine"
    # an error raised deeper in the call chain is caught too, and the call stack is unwound
    vm = VM()
    thrower = closure(proto([(THROW, 1, 0, 0, 0)], params=("this", "x"), name="thrower"), vm)
    catcher = proto([(PUSHTRAP, 5, 5, 0, 0), (MOVE, 2, 1, 0, 0), (MOVE, 3, 0, 0, 0), (LOADINT, 4, 42, 0, 0),
                     (CALL, NONE, 2, 3, 2), (POPTRAP, 1, 0, 0, 0), (RETURN, 1, 5, 0, 0)], params=("this", "fn"))
    assert run(catcher, thrower, vm=vm) == 42 and vm.stack == []
    with pytest.raises(SqError) as caught:
        thrower.invoke(None, ("up",))
    # an error nobody caught leaves its frames on the call stack: whoever catches it reads the trace there
    assert caught.value.value == "up" and vm.stack == [thrower]


def test_classes_instances_typeof_clone():
    vm = VM()
    get_x = proto([(GETK, 1, 0, 0, 0), (RETURN, 1, 1, 0, 0)], literals=("x",), name="getX")
    # class { x = 5; function getX() { return x } }
    make = proto([(NEWOBJ, 1, -1, NONE, 2), (LOAD, 2, 0, 0, 0), (LOADINT, 3, 5, 0, 0), (NEWSLOTA, 0, 1, 2, 3),
                  (LOAD, 2, 1, 0, 0), (CLOSURE, 3, 0, 0, 0), (NEWSLOTA, 0, 1, 2, 3), (RETURN, 1, 1, 0, 0)],
                 literals=("x", "getX"), functions=(get_x,))
    cls = run(make, vm=vm)
    assert type(cls) is SqClass
    # local o = cls(); return [o.getX(), o instanceof cls, typeof o, 5 instanceof cls]
    use = proto([(MOVE, 2, 1, 0, 0), (MOVE, 3, 0, 0, 0), (CALL, 2, 2, 3, 1), (PREPCALLK, 4, 0, 2, 5), (CALL, 4, 4, 5, 1),
                 (INSTANCEOF, 6, 1, 2, 0), (TYPEOF, 7, 2, 0, 0), (LOADINT, 8, 5, 0, 0), (INSTANCEOF, 8, 1, 8, 0),
                 (NEWOBJ, 9, 4, 0, 1), (APPENDARRAY, 9, 4, 0, 0), (APPENDARRAY, 9, 6, 0, 0), (APPENDARRAY, 9, 7, 0, 0),
                 (APPENDARRAY, 9, 8, 0, 0), (APPENDARRAY, 9, 2, 0, 0), (RETURN, 1, 9, 0, 0)],
                literals=("getX",), params=("this", "cls"))
    x, is_inst, kind, five, inst = run(use, cls, vm=vm)
    assert (x, is_inst, kind, five) == (5, True, "instance", False) and type(inst) is SqInstance
    with pytest.raises(SqError):                    # instanceof needs a class on the right
        run(proto([(INSTANCEOF, 2, 1, 1, 0), (RETURN, 1, 2, 0, 0)], params=("this", "a")), 5, vm=vm)
    # clone copies a table; array literals take stack values, literals, ints, floats and bools
    cl = proto([(CLONE, 2, 1, 0, 0), (RETURN, 1, 2, 0, 0)], params=("this", "t"))
    src = table(a=1)
    copy = run(cl, src, vm=vm)
    assert copy is not src and copy.get("a") == 1
    arr = proto([(NEWOBJ, 1, 5, 0, 1), (APPENDARRAY, 1, 0, 1, 0), (APPENDARRAY, 1, -3, 2, 0),
                 (APPENDARRAY, 1, struct.unpack("<i", struct.pack("<f", 1.5))[0], 3, 0), (APPENDARRAY, 1, 1, 4, 0),
                 (RETURN, 1, 1, 0, 0)], literals=("lit",))
    assert run(arr, vm=vm) == ["lit", -3, 1.5, True]


def test_generator_functions_give_a_generator_object_without_running():
    gen = closure(proto([(THROW, 0, 0, 0, 0)], generator=True))
    assert typeof(gen.invoke(None, ())) == "generator"
