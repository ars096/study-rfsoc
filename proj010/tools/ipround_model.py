import numpy as np
rng=np.random.default_rng(0)
N=8192; P=16; M=512
def fft_round(x, mode):
    # radix-2 DIT, round after each twiddle product (unscaled: LSB stays at input LSB)
    n=len(x); a=x.astype(complex)
    idx=np.array([int(format(i,'09b')[::-1],2) for i in range(n)]); a=a[idx]
    L=2
    while L<=n:
        h=L//2; w=np.exp(-2j*np.pi*np.arange(h)/L)
        w=(np.round(w.real*2**17)+1j*np.round(w.imag*2**17))/2**17
        a=a.reshape(-1,L)
        t=a[:,h:]*w
        if mode=='round': t=np.round(t.real)+1j*np.round(t.imag)
        a=np.concatenate([a[:,:h]+t,a[:,:h]-t],axis=1).reshape(-1)
        L*=2
    return a
def trial(sig):
    x=np.clip(np.round(rng.normal(0,sig,N)),-8192,8191)
    Xe=np.fft.fft(x)[:4096]
    Y=np.array([fft_round(x[p::16],'round') for p in range(P)])  # lane outputs
    Y=np.round(Y.real)+1j*np.round(Y.imag)
    k1=np.arange(M)
    X=np.zeros(N,complex)
    for k2 in range(16):
        acc=0
        for p in range(P):
            acc=acc+np.exp(-2j*np.pi*p*(k1+512*k2)/N)*Y[p]
        X[k1+512*k2]=acc
    d=np.abs(np.abs(X[:4096])-np.abs(Xe))
    return d.mean(), d.max(), np.abs(Xe).mean()
for s in (5.8, 58, 580):
    print(s, trial(s))
