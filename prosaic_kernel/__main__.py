from ipykernel.kernelapp import IPKernelApp
from .kernel import ProsaicKernel
IPKernelApp.launch_instance(kernel_class=ProsaicKernel)
