#include <Python.h>

static PyObject *vml_check_variable(PyObject *self, PyObject *args)
{
    PyObject *frame, *reference_prev, *reference_curr, *key, *tmp_domain;
    if (!PyArg_ParseTuple(args, "OOOO", &frame, &reference_prev, &key, &tmp_domain)) {return NULL;}

    const char domain = PyUnicode_AsUTF8(tmp_domain)[0];

    if (domain == 'L'){
        PyObject *locals = PyFrame_GetLocals((PyFrameObject *)frame);

        if (locals){
            reference_curr = PyDict_GetItem(locals, key);
            Py_XDECREF(locals);
        }
    }
    else{
        PyObject *globals = PyFrame_GetGlobals((PyFrameObject *)frame);

        if (globals){
            reference_curr = PyDict_GetItem(globals, key);
            Py_XDECREF(globals);
        }
    }

    if (reference_curr == NULL){
        //1st step : Checking Existance
        Py_RETURN_NONE;
    }
    
    if (reference_curr != reference_prev){
        //2nd step : Checking Reference in Stack
        Py_RETURN_TRUE;
    }

    //3rd step : Checking Data in Heap
    int diff = PyObject_RichCompareBool(reference_curr, reference_prev, Py_NE);
    if (diff == 1){
        Py_RETURN_TRUE;
    }
    else if (diff == -1){
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