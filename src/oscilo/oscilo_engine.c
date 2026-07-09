#include <Python.h>

typedef enum {
    LOCAL = 0,
    GLOBAL = 1
} ScopeType;

static PyObject *get_scope_dict(PyObject *frame, ScopeType domain)
{
    // Select the dictionary that should be inspected for the requested scope.
    if (domain == LOCAL) {
        return PyFrame_GetLocals((PyFrameObject *)frame);
    }

    return PyFrame_GetGlobals((PyFrameObject *)frame);
}

static PyObject *get_reference_from_scope(PyObject *scope_dict, PyObject *key)
{
    PyObject *reference = NULL;

#if PY_VERSION_HEX >= 0x030D0000
    // Python 3.13+ may expose frame locals through a proxy, so use GetItem.
    reference = PyObject_GetItem(scope_dict, key);
    if (reference == NULL) {
        PyErr_Clear();
    }
#else
    // PyDict_GetItem returns a borrowed reference, so incref before returning.
    reference = PyDict_GetItem(scope_dict, key);
    Py_XINCREF(reference);
#endif

    return reference;
}

static int is_immutable_value(PyObject *value)
{
    return PyLong_Check(value) ||
           PyUnicode_Check(value) ||
           PyFloat_Check(value) ||
           PyBool_Check(value) ||
           value == Py_None;
}

static int has_different_size(PyObject *current_value, PyObject *previous_snapshot)
{
    // Fast-path: size changes prove container mutation without full comparison.
    if (PyList_Check(current_value)) {
        return PyList_GET_SIZE(current_value) != PyList_GET_SIZE(previous_snapshot);
    }

    if (PyDict_Check(current_value)) {
        return PyDict_Size(current_value) != PyDict_Size(previous_snapshot);
    }

    if (PySet_Check(current_value) || PyFrozenSet_Check(current_value)) {
        return PySet_GET_SIZE(current_value) != PySet_GET_SIZE(previous_snapshot);
    }

    if (PyTuple_Check(current_value)) {
        return PyTuple_GET_SIZE(current_value) != PyTuple_GET_SIZE(previous_snapshot);
    }

    return 0;
}

static int compare_mutable_value(PyObject *current_value, PyObject *previous_snapshot)
{
    if (has_different_size(current_value, previous_snapshot)) {
        return 1;
    }

    return PyObject_RichCompareBool(current_value, previous_snapshot, Py_NE);
}

static PyObject *oscilo_check_variable(PyObject *self, PyObject *args)
{
    PyObject *frame;
    PyObject *reference_prev;
    PyObject *last_val_copy;
    PyObject *key;
    PyObject *reference_curr = NULL;
    PyObject *scope_dict = NULL;
    int domain_val;
    int diff;
    ScopeType domain;

    if (!PyArg_ParseTuple(args, "OOOiO", &frame, &reference_prev, &last_val_copy, &domain_val, &key)) {
        return NULL;
    }

    domain = (ScopeType)domain_val;
    scope_dict = get_scope_dict(frame, domain);

    if (scope_dict != NULL) {
        reference_curr = get_reference_from_scope(scope_dict, key);
        Py_DECREF(scope_dict);
    }

    if (reference_curr == NULL) {
        PyErr_Clear();
        Py_RETURN_NONE;
    }

    if (reference_curr != reference_prev) {
        Py_DECREF(reference_curr);
        Py_RETURN_TRUE;
    }

    // Immutable values cannot change in place when the reference is unchanged.
    if (is_immutable_value(reference_curr)) {
        Py_DECREF(reference_curr);
        Py_RETURN_FALSE;
    }

    diff = compare_mutable_value(reference_curr, last_val_copy);
    Py_DECREF(reference_curr);

    if (diff == 1) {
        Py_RETURN_TRUE;
    }

    if (diff == -1) {
        return NULL;
    }

    Py_RETURN_FALSE;
}

static PyMethodDef VmlMethods[] = {
    {"check_variable", oscilo_check_variable, METH_VARARGS, "Check variable status"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef vmlmodule = {
    PyModuleDef_HEAD_INIT,
    "vmlog_engine",
    NULL,
    -1,
    VmlMethods
};

PyMODINIT_FUNC PyInit_oscilo_engine(void)
{
    return PyModule_Create(&vmlmodule);
}