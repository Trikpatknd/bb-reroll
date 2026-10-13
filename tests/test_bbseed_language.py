"""Language-level behaviour of the Squirrel interpreter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbseed.sq.vm import VM
from bbseed.sq.runtime import SqError


def run(src):
    vm = VM()
    out = []
    vm.print_fn = out.append
    vm.run(src, "test.nut")
    return out


def test_arithmetic_and_types():
    assert run('print(7 / 2); print(-7 / 2); print(7 % 3); print(-7 % 3); print(7 / 2.0); print(1 + 2.5)') == \
        ["3", "-3", "1", "-1", "3.5", "3.5"]
    assert run('print(2147483647 + 1); print(typeof 1); print(typeof 1.0); print(typeof "a"); print(typeof null)') == \
        ["-2147483648", "integer", "float", "string", "null"]
    assert run('print(1 == 1.0); print("a" + 1 + 2.5); print(0.1 + 0.2); print(10000000.0)') == \
        ["true", "a12.5", "0.3", "1e+07"]


def test_locals_closures_and_loops():
    src = '''
    local fns = [];
    for (local i = 0; i < 3; i++) { local j = i * 10; fns.push(function () { return j; }); }
    foreach (f in fns) print(f());
    local counter = function () { local n = 0; return function () { n += 1; return n; } }();
    counter(); print(counter());
    local total = 0;
    foreach (i, v in [5, 6, 7]) { if (i == 1) continue; total += v; }
    print(total);
    local k = 0; while (true) { k++; if (k > 4) break; } print(k);
    '''
    assert run(src) == ["0", "10", "20", "2", "12", "5"]


def test_tables_this_and_root_fallback():
    src = '''
    ::G <- 5;
    local t = { a = 1, function get() { return this.a + G; }, function viaThis() { return this.G; } };
    print(t.get()); print(t.viaThis()); print("a" in t); print("zz" in t);
    t.b <- 2; t.a = 10; print(t.a + t.b); delete t.b; print("b" in t);
    function t::added() { return 42; }
    print(t.added());
    local threw = false; try { t.nope = 1; } catch (e) { threw = true; } print(threw);
    '''
    assert run(src) == ["6", "5", "true", "false", "12", "false", "42", "true"]


def test_switch_ternary_logic():
    src = '''
    local function f(x) { switch (x) { case 1: return "one"; case 2: case 3: return "few"; default: return "many"; } }
    print(f(1) + f(3) + f(9));
    print(null || "dflt"); print(0 && "no"); print(5 > 3 ? "y" : "n");
    '''
    assert run(src) == ["onefewmany", "dflt", "0", "y"]


def test_strings_arrays_format():
    src = '''
    local s = "Hello World";
    print(s.len()); print(s.slice(0, 5)); print(s.slice(-5)); print(s.find("World")); print(s.find("zz") == null);
    print(s.tolower()); print("12".tointeger() + 1); print(format("%d-%s-%.2f-%03d", 5, "x", 1.5, 7));
    local a = [3, 1, 2]; a.sort(); print(a[0] + "" + a[1] + a[2]);
    a.sort(@(x, y) y <=> x); print(a[0]); a.push(9); print(a.len()); print(a.pop()); print(a.find(1));
    a.insert(0, 7); print(a.remove(0)); print(a.map(@(v) v * 2)[0]); print([1,2,3,4].filter(@(i, v) v % 2 == 0).len());
    print([1,2,3].reduce(@(p, c) p + c)); local b = clone a; b.push(1); print(a.len() != b.len());
    '''
    assert run(src) == ["11", "Hello", "World", "6", "true", "hello world", "13", "5-x-1.50-007",
                        "123", "3", "4", "9", "2", "7", "6", "2", "6", "true"]


def test_classes():
    src = '''
    class Animal { name = null; constructor(n) { this.name = n; } function speak() { return name + " makes a sound"; } }
    class Dog extends Animal { function speak() { return name + " barks"; } }
    local d = Dog("Rex"); print(d.speak()); print(d instanceof Animal); print(typeof d);
    ::Box <- class { v = 0; function _tostring() { return "Box(" + v + ")"; } };
    local b = ::Box(); b.v = 3; print("" + b);
    '''
    assert run(src) == ["Rex barks", "true", "instance", "Box(3)"]


def test_function_helpers_and_varargs():
    src = '''
    local function sum(...) { local t = 0; foreach (v in vargv) t += v; return t; }
    print(sum(1, 2, 3)); print(sum.call(this, 4, 5)); print(sum.acall([this, 1, 1]));
    local obj = { x = 7 }; local getx = function () { return this.x; }; print(getx.bindenv(obj)());
    local function dflt(a, b = 10) { return a + b; } print(dflt(1)); print(dflt(1, 2));
    '''
    assert run(src) == ["6", "9", "2", "7", "11", "3"]


def test_tail_call_replaces_frame_for_getstackinfos():
    src = '''
    local function who() { return getstackinfos(2).func; }
    local function wrapper() { return who(); }      // tail call: wrapper's frame is gone
    local function outer() { local r = wrapper(); return "" + r; }
    print(outer());
    '''
    assert run(src) == ["outer"]


def test_errors_are_catchable():
    src = '''
    try { local t = {}; t.missing.x = 1; } catch (e) { print(e); }
    try { throw "boom"; } catch (e) { print(e); }
    try { local a = [1]; a[5]; } catch (e) { print(typeof e); }
    '''
    assert run(src) == ["the index 'missing' does not exist", "boom", "string"]


def test_weird_assignment_in_condition_is_accepted():
    # Legends' hunter_building.nut has `else if (typeof _m = "integer")`.
    assert run('local m = 5; if (typeof m = "integer") print("ok");') == ["ok"]
