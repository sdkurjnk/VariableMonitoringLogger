#include <Python.h>

typedef enum {
    LOCAL = 0,
    GLOBAL = 1
} ScopeType;

static PyObject *vml_check_variable(PyObject *self, PyObject *args)
{
    PyObject *frame, *reference_prev, *last_val_copy, *key;
    int domain_val;
    
    if (!PyArg_ParseTuple(args, "OOOiO", &frame, &reference_prev, &last_val_copy, &domain_val, &key)) {
        return NULL;
    }

    ScopeType domain = (ScopeType)domain_val;
    PyObject *reference_curr = NULL;
    PyObject *scope_dict = NULL;

    // LOCAL인지 GLOBAL인지에 따라 프레임에서 가져옴
    if (domain == LOCAL) {
        scope_dict = PyFrame_GetLocals((PyFrameObject *)frame);
    } else {
        scope_dict = PyFrame_GetGlobals((PyFrameObject *)frame);
    }

    if (scope_dict) {
#if PY_VERSION_HEX >= 0x030D0000
        reference_curr = PyObject_GetItem(scope_dict, key);
        if (reference_curr == NULL) {
            PyErr_Clear();
        }
#else
        reference_curr = PyDict_GetItem(scope_dict, key);
        Py_XINCREF(reference_curr); 
#endif
        Py_DECREF(scope_dict);
    }

    // Step1 : Checking existance
    if (reference_curr == NULL) {
        PyErr_Clear();
        Py_RETURN_NONE;
    }

    // Step2 : Checking reference in Stack
    if (reference_curr != reference_prev) {
        Py_DECREF(reference_curr);
        Py_RETURN_TRUE;
    }

    // Step3 : Checking immutability
    if (PyLong_Check(reference_curr) || 
        PyUnicode_Check(reference_curr) || 
        PyFloat_Check(reference_curr) || 
        PyBool_Check(reference_curr) || 
        reference_curr == Py_None) {
        Py_DECREF(reference_curr); 
        Py_RETURN_FALSE; 
    }

    // Step4 : Checking Data in Heap
    int diff = PyObject_RichCompareBool(reference_curr, last_val_copy, Py_NE);
    Py_DECREF(reference_curr);
    
    if (diff == 1) {
        Py_RETURN_TRUE;
    } else if (diff == -1) {
        return NULL;
    }

    Py_RETURN_FALSE;
}

static PyMethodDef VmlMethods[] = {
    {"check_variable", vml_check_variable, METH_VARARGS, "Check variable status"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef vmlmodule = {
    PyModuleDef_HEAD_INIT,
    "vml_engine",
    NULL,
    -1,
    VmlMethods
};

PyMODINIT_FUNC PyInit_vml_engine(void) {
    return PyModule_Create(&vmlmodule);
}