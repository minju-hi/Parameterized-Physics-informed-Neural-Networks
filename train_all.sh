for seed in 0
do
    for init_cond in 'gauss_pi_2'
    do
        for pde_type in 'all'
        do
            for coeff_range in 5
            do
                for epoch in 2000
                do
                    CUDA_VISIBLE_DEVICES=0 python -u train.py --init_cond $init_cond --pde_type $pde_type --coeff_range $coeff_range --seed $seed --epoch $epoch > ./log/train/{$init_cond}_{$pde_type}_{$coeff_range}_{$seed}_{$epoch}.csv
                done
            done
        done
    done
done