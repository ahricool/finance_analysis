<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';

type Particle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
  baseAlpha: number;
};

const PARTICLE_COLORS = ['14, 165, 233', '16, 185, 129', '59, 130, 246', '139, 92, 246'];

function createParticle(canvas: HTMLCanvasElement): Particle {
  return {
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - 0.5) * 0.5,
    vy: (Math.random() - 0.5) * 0.5,
    radius: Math.random() * 2.0 + 1.0,
    color: PARTICLE_COLORS[Math.floor(Math.random() * PARTICLE_COLORS.length)]!,
    baseAlpha: Math.random() * 0.6 + 0.2,
  };
}

function updateParticle(particle: Particle, canvas: HTMLCanvasElement) {
  particle.x += particle.vx;
  particle.y += particle.vy;

  if (particle.x < 0 || particle.x > canvas.width) {
    particle.vx *= -1;
  }
  if (particle.y < 0 || particle.y > canvas.height) {
    particle.vy *= -1;
  }
}

function drawParticle(ctx: CanvasRenderingContext2D, particle: Particle) {
  ctx.beginPath();
  ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${particle.color}, ${particle.baseAlpha})`;
  ctx.fill();
}

const canvasRef = ref<HTMLCanvasElement | null>(null);

let animationFrameId = 0;
const cleanups: (() => void)[] = [];

onMounted(() => {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  let particles: Particle[] = [];
  const mouse = { x: -1000, y: -1000 };

  function initParticles() {
    particles = [];
    const numParticles = Math.floor((canvas!.width * canvas!.height) / 10000);
    for (let i = 0; i < numParticles; i++) {
      particles.push(createParticle(canvas!));
    }
  }

  function resize() {
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    initParticles();
  }

  function drawLines(c: CanvasRenderingContext2D) {
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]!;
      const dxMouse = p.x - mouse.x;
      const dyMouse = p.y - mouse.y;
      const distMouse = Math.sqrt(dxMouse * dxMouse + dyMouse * dyMouse);

      if (distMouse > 0 && distMouse < 250) {
        c.beginPath();
        const opacity = 0.8 * (1 - distMouse / 250);
        c.strokeStyle = `rgba(6, 182, 212, ${opacity})`;
        c.lineWidth = 2.0;
        c.moveTo(p.x, p.y);
        c.lineTo(mouse.x, mouse.y);
        c.stroke();

        const force = (250 - distMouse) / 250;
        p.x += (dxMouse / distMouse) * force * 2.0;
        p.y += (dyMouse / distMouse) * force * 2.0;
      }

      for (let j = i + 1; j < particles.length; j++) {
        const q = particles[j]!;
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 150) {
          c.beginPath();
          const opacity = 0.3 * (1 - dist / 150);
          c.strokeStyle = `rgba(255, 255, 255, ${opacity})`;
          c.lineWidth = 0.8;
          c.moveTo(p.x, p.y);
          c.lineTo(q.x, q.y);
          c.stroke();
        }
      }
    }
  }

  function animate() {
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach((particle) => {
      updateParticle(particle, canvas);
      drawParticle(ctx, particle);
    });
    drawLines(ctx);

    animationFrameId = requestAnimationFrame(animate);
  }

  const handleResize = () => resize();
  const handleMouseMove = (e: MouseEvent) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  };
  const handleMouseOut = () => {
    mouse.x = -1000;
    mouse.y = -1000;
  };

  window.addEventListener('resize', handleResize);
  window.addEventListener('mousemove', handleMouseMove);
  window.addEventListener('mouseout', handleMouseOut);

  cleanups.push(() => window.removeEventListener('resize', handleResize));
  cleanups.push(() => window.removeEventListener('mousemove', handleMouseMove));
  cleanups.push(() => window.removeEventListener('mouseout', handleMouseOut));

  resize();
  animate();
});

onUnmounted(() => {
  cancelAnimationFrame(animationFrameId);
  cleanups.forEach((fn) => fn());
  cleanups.length = 0;
});
</script>

<template>
  <canvas
    ref="canvasRef"
    class="pointer-events-none absolute inset-0 z-0"
    style="background: transparent"
  />
</template>
