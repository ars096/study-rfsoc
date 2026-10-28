// proj035 L-2: CPU から見た DDR の読みの遅れ（ポインタの追いかけ、64 MiB）と書き・写しの速さ（4 MiB）
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
int main(int argc,char**argv){
  int secs=argc>1?atoi(argv[1]):10;
  size_t N=(64u<<20)/sizeof(void*); void**a=malloc(N*sizeof(void*)); size_t*idx=malloc(N*sizeof(size_t));
  size_t step=64/sizeof(void*); size_t M=N/step;
  for(size_t i=0;i<M;i++)idx[i]=i*step;
  srand(1); for(size_t i=M-1;i>0;i--){size_t j=rand()%(i+1),t=idx[i];idx[i]=idx[j];idx[j]=t;}
  for(size_t i=0;i<M;i++)a[idx[i]]=&a[idx[(i+1)%M]];
  free(idx);
  size_t B=4u<<20; char*s=malloc(B),*d=malloc(B); memset(s,1,B); memset(d,2,B);
  double t_end=now()+secs, lat_sum=0, wr_sum=0, cp_sum=0; int n=0; void**p=a;
  while(now()<t_end){
    double t0=now(); for(int k=0;k<2000000;k++)p=(void**)*p; double t1=now();
    for(int r=0;r<8;r++)memset(d,r,B); double t2=now();
    for(int r=0;r<8;r++)memcpy(d,s,B); double t3=now();
    lat_sum+=(t1-t0)/2e6*1e9; wr_sum+=8.0*B/(t2-t1)/1e9; cp_sum+=8.0*B/(t3-t2)/1e9; n++;
  }
  printf("lat %.1f ns  memset %.2f GB/s  memcpy %.2f GB/s  (n=%d, %p)\n",lat_sum/n,wr_sum/n,cp_sum/n,n,(void*)p);
  return 0;
}
